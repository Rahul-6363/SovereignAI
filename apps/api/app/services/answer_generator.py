"""Answer generator — grounded, streaming chat completion.

Produces SSE event dicts: status / evidence / token / done.

When the configured chat model is unavailable (air-gap demo before pull),
a deterministic template answer is built directly from the evidence packet
so the demo still streams a credible, provable answer.
"""
from __future__ import annotations

import asyncio
import json
import re

from sqlmodel import Session, select

from app.config import Settings
from app.services import audit
from app.services.confidence import answer_confidence
from app.services.evidence_builder import build_evidence_packet, attach_document_meta
from app.services.graph_memory import GraphMemory
from app.services.hybrid_retriever import HybridRetriever
from app.services.ollama_gateway import OllamaGateway
from app.services.query_router import classify, choose_model
from packages.prompts import GROUNDED_ANSWER_PROMPT, prompt_version

UNKNOWN = "unknown"


# Fields the model can actually reason with. Everything else in the packet —
# bboxes, row ids, document ids — exists so the UI can resolve a citation to a
# place on a drawing. Sending it to the model costs prompt tokens on every
# turn and buys nothing, which on CPU is seconds per question.
_MODEL_FIELDS = (
    "source_type", "entity", "relation", "target", "text", "document", "page",
)


def _tags_present(packet: dict, tags: list[str]) -> bool:
    """Is any tag the question named actually IN the retrieved evidence?

    "Is the packet non-empty" is not the same question. Hybrid retrieval
    always returns its nearest neighbours, so asking about a tag that does not
    exist still comes back full — of other equipment. Handed that, the model
    answered about XYZ-999 using P-101's evidence, confidently and with a high
    confidence score. The tag itself has to appear before an answer is
    grounded in any useful sense.
    """
    if not tags:
        return True
    haystack = " ".join(
        str(item.get(field, ""))
        for item in (packet.get("answer_context") or [])
        for field in ("entity", "target", "text")
    ).upper()
    return any(tag.upper() in haystack for tag in tags)


def _packet_for_model(packet: dict) -> dict:
    """The evidence packet trimmed to what the model needs to read.

    The full packet still goes to the UI in the `evidence` event, so citations
    keep their coordinates; this affects only what is put in the prompt.
    """
    return {
        "query_intent": packet.get("query_intent", ""),
        "retrieved_from": packet.get("retrieved_from", ""),
        "answer_context": [
            {k: item[k] for k in _MODEL_FIELDS if item.get(k) not in (None, "")}
            for item in (packet.get("answer_context") or [])[:12]
        ],
    }


class AnswerGenerator:
    def __init__(
        self,
        settings: Settings,
        gateway: OllamaGateway,
        retriever: HybridRetriever,
        graph: GraphMemory,
    ):
        self.settings = settings
        self.gateway = gateway
        self.retriever = retriever
        self.graph = graph

    # ── main streaming entry point ────────────────────────────
    async def stream_chat(
        self,
        session: Session,
        project_id: int,
        question: str,
        top_k: int = 10,
        session_id: str = "web",
        history: list[dict] | None = None,
    ):
        yield {"type": "status", "stage": "intent", "detail": "Understanding the question…"}
        route = classify(question)
        intent = route["intent"]
        audit.record_event(
            user_action="chat",
            model=self.settings.ollama_chat_model,
            session_id=session_id,
            result_status="route:" + intent,
        )

        # PID_VISUAL: still retrieve the same memory; the UI will highlight.
        yield {"type": "status", "stage": "retrieving", "detail": "Searching plant memory…"}
        # A follow-up such as "and its upstream?" carries no tag of its own;
        # retrieval widens to the last user turn that did mention one.
        retrieval_query = _retrieval_query(question, history)
        results = await self.retriever.retrieve(
            session, project_id, retrieval_query, top_k=top_k
        )

        packet = build_evidence_packet(session, project_id, question, self.graph, results)
        packet["query_intent"] = intent
        packet = attach_document_meta(session, packet)

        yield {"type": "status", "stage": "grounding", "detail": "Checking P&ID evidence…"}
        await asyncio.sleep(0.05)

        model = choose_model(self.settings, intent, bool(route["tags"]))
        yield {"type": "evidence", "packet": packet}

        # ── no evidence: say so, do not improvise ─────────────
        # Handing an empty packet to a small model produces confident fiction —
        # asked about a tag this project has never seen, it described a reactor
        # coolant line that exists nowhere. A question about a named plant item
        # with nothing behind it has exactly one honest answer.
        if route["tags"] and not _tags_present(packet, route["tags"]):
            message = self._no_evidence_message(session, project_id, route["tags"])
            for i in range(0, len(message), 48):
                yield {"type": "token", "text": message[i : i + 48]}
                await asyncio.sleep(0.008)
            audit.record_event(
                user_action="answer", model=UNKNOWN, session_id=session_id,
                retrieval_count=0, result_status="no_evidence",
            )
            yield {
                "type": "done", "message": message, "confidence": 0.0,
                "claims": [], "sources": [], "intent": intent,
                "model": UNKNOWN, "grounded": False,
                "prompt_version": prompt_version("grounded_answer"),
            }
            return

        # ── generate tokens ───────────────────────────────────
        holder: dict = {}
        if await self.gateway.model_installed(self.settings.ollama_chat_model):
            yield {"type": "status", "stage": "answering", "detail": f"Streaming answer ({model})…"}
            async for ev in self._stream_llm(
                packet, question, model, intent, holder, history
            ):
                yield ev
            message, llm_used = holder.get("message", ""), holder.get("model", model)
            # Small local models paraphrase evidence and can drop tags, so the
            # deterministic facts are always appended as the verifiable body.
            if not holder.get("skip_facts"):
                facts = self._facts_section(packet, question, intent)
                if facts:
                    for i in range(0, len(facts), 48):
                        chunk = facts[i : i + 48]
                        yield {"type": "token", "text": chunk}
                        await asyncio.sleep(0.012)
                    message += facts
        else:
            async for ev in self._stream_template(packet, question, intent, holder):
                yield ev
            message, llm_used = holder.get("message", ""), holder.get("model", UNKNOWN)

        # ── finalize ───────────────────────────────────────────
        claims, sources = self._shape_claims_and_sources(packet)
        confidence = answer_confidence(
            [c["confidence"] for c in packet["answer_context"] if c.get("confidence")]
        )
        audit.record_event(
            user_action="answer",
            model=llm_used,
            session_id=session_id,
            retrieval_count=len(results),
            result_status="ok" if confidence > 0 else "empty",
        )
        yield {
            "type": "done",
            "message": message,
            "confidence": round(confidence, 3),
            "claims": claims,
            "sources": sources,
            "intent": intent,
            "model": llm_used,
            "prompt_version": prompt_version("grounded_answer"),
        }

    # ── LLM path ──────────────────────────────────────────────
    async def _stream_llm(
        self,
        packet,
        question: str,
        model: str,
        intent: str,
        result: dict,
        history: list[dict] | None = None,
    ):
        rendered = json.dumps(
            _packet_for_model(packet), ensure_ascii=False, separators=(",", ":")
        )
        prompt = GROUNDED_ANSWER_PROMPT.format(evidence_packet=rendered, question=question)
        messages = [
            {
                "role": "system",
                "content": (
                    "You ground every statement in the supplied evidence packet. "
                    "Answer in at most 3 short sentences. Mention ONLY tags that "
                    "appear in the evidence packet — never invent or substitute "
                    "tags. A 'Verified from Plant Memory' section with the exact "
                    "facts is appended automatically; do not repeat lists."
                ),
            },
        ]
        # Prior turns give the model the referents a follow-up depends on;
        # the evidence packet still decides what it is allowed to assert.
        for turn in (history or [])[-6:]:
            messages.append({"role": turn["role"], "content": turn["content"][:1500]})
        messages.append({"role": "user", "content": prompt})
        parts: list[str] = []
        try:
            async for token in self.gateway.chat_stream(
                messages,
                model,
                {
                    "temperature": 0.2,
                    "num_predict": self.settings.ollama_num_predict,
                },
            ):
                parts.append(token)
                yield {"type": "token", "text": token}
        except Exception as exc:
            result["skip_facts"] = True  # template fallback already includes facts
            fallback_holder: dict = {}
            async for _ev in self._stream_template(packet, question, intent, fallback_holder):
                pass
            if not parts:
                fallback = fallback_holder.get("message", "")
                yield {"type": "token", "text": fallback}
                # The fallback IS the answer now — keep it in `message` so the
                # persisted turn and the UI's `done` event are not blanked out.
                parts.append(fallback)
                result["model"] = UNKNOWN
            else:
                yield {"type": "status", "detail": f"Model error: {exc}. Partial answer shown."}
        result["message"] = "".join(parts)
        result.setdefault("model", model)

    def _no_evidence_message(
        self, session: Session, project_id: int, tags: list[str]
    ) -> str:
        """State plainly that the project holds nothing on these tags.

        Naming what the project *does* contain turns a dead end into a usable
        one: most of the time the tag is right and the drawing is simply in a
        different project, which the list makes obvious immediately.
        """
        from app.models import Entity

        wanted = ", ".join(tags)
        known = session.exec(
            select(Entity.canonical_tag)
            .where(Entity.project_id == project_id)
            .distinct()
            .order_by(Entity.canonical_tag)
            .limit(24)
        ).all()

        if not known:
            return (
                f"I have no evidence for **{wanted}** — this project has no "
                "drawings or documents ingested yet.\n\nUpload a P&ID and I "
                "will answer from it."
            )
        return (
            f"I have no evidence for **{wanted}** in this project, so I will "
            "not guess at an answer.\n\n**Tags this project does contain:** "
            + ", ".join(known)
            + ("…" if len(known) == 24 else "")
            + "\n\nIf the drawing you mean is in another project, switch to it; "
            "otherwise upload it here."
        )

    def _facts_section(self, packet, question: str, intent: str) -> str:
        """Deterministic fact block appended after the LLM lead (grounding)."""
        blocks = _template_answer(self.graph, packet, question, intent)
        body = [b for b in blocks[1:] if not b.startswith("\n_Note:")]
        if not body:
            return ""
        return "\n\n**Verified from Plant Memory:**\n" + "".join(body)
# ── deterministic template path (offline / air-gap) ───────
    async def _stream_template(self, packet, question: str, intent: str, result: dict):
        blocks = _template_answer(self.graph, packet, question, intent)
        text = "".join(blocks)
        for i in range(0, len(text), 48):
            chunk = text[i : i + 48]
            yield {"type": "token", "text": chunk}
            await asyncio.sleep(0.012)
        result["message"] = text
        result["model"] = UNKNOWN

    # ── structured shape (README section 27) ─────────────────
    def _shape_claims_and_sources(self, packet) -> tuple[list[dict], list[dict]]:
        claims: list[dict] = []
        sources: list[dict] = []
        for item in packet["answer_context"][:12]:
            if item.get("source_type") == "graph":
                claim_text = f"{item['entity']} {item['relation']} {item['target']}"
                claims.append(
                    {
                        "text": claim_text,
                        "confidence": item.get("confidence", 0.5),
                        "evidence_ids": [claim_text],
                    }
                )
                sources.append(
                    {
                        "document": "",
                        "page": 0,
                        "bbox": None,
                        "source_type": "graph",
                        "relation": claim_text,
                    }
                )
            elif item.get("source_type") == "pid":
                claims.append(
                    {
                        "text": f"{item.get('entity')} located at {item.get('bbox')}",
                        "confidence": item.get("confidence", 0.5),
                        "evidence_ids": [str(item.get("entity"))],
                    }
                )
                sources.append(
                    {
                        "document": item.get("document") or "",
                        "page": item.get("page") or 0,
                        "bbox": item.get("bbox"),
                        "source_type": "pid",
                    }
                )
        return claims, sources
# ── offline template answer builder ───────────────────────────
def _template_answer(graph: GraphMemory, packet: dict, question: str, intent: str) -> list[str]:
    ql = question.lower()
    ctx = [
        c
        for c in ((packet or {}).get("answer_context") or [])
        if c.get("entity") or c.get("target")
    ]

    blocks: list[str] = []
    if not ctx:
        blocks.append(
            "I could not confidently resolve this from plant memory. "
            "No matching entity or relationship is present in the extracted evidence."
        )
        return blocks

    blocks.append("Based on the Plant Memory evidence, here is what I found:\n\n")

    mentioned = _mention(ql)
    if mentioned and mentioned in graph.graph:
        node = graph.entity(mentioned) or {}
        etype = node.get("type", "tag")
        label = node.get("label", mentioned)
        blocks.append(f"**{mentioned}** is a **{etype}** ({label}).\n\n")

        if any(k in ql for k in ("upstream", "before")):
            ups = graph.upstream(mentioned)
            if ups:
                blocks.append("Upstream of it:\n")
                for u in ups:
                    blocks.append(f"- `{u['tag']}` via `{u['relation']}`\n")
            else:
                blocks.append("No upstream connections were extracted for it.\n")
            blocks.append("\n")

        if any(k in ql for k in ("downstream", "connected", "associated")):
            downs = graph.neighbors(mentioned)
            if downs:
                blocks.append("Downstream / connected:\n")
                for d in downs:
                    blocks.append(f"- `{d['tag']}` via `{d['relation']}`\n")
            blocks.append("\n")

    instruments = [
        (c["entity"], c["target"], c.get("relation"))
        for c in ctx
        if c.get("source_type") == "graph" and c.get("relation") == "HAS_INSTRUMENT"
    ]
    if "instrument" in ql or instruments:
        unique = sorted({t for _, t, _ in instruments})
        if unique:
            blocks.append("Associated instruments:\n")
            for t in unique:
                blocks.append(f"- `{t}`\n")
            blocks.append("\n")

    if intent == "PID_VISUAL" or "where" in ql:
        pid_sources = [c for c in ctx if c.get("source_type") in ("pid", "chunk")]
        if pid_sources:
            blocks.append("P&ID evidence (highlighted in the drawing):\n")
            for c in pid_sources[:5]:
                bbox = c.get("bbox")
                page = c.get("page", "")
                blocks.append(
                    f"- `{c.get('entity') or c.get('text', '')}` at bbox {bbox}"
                    + (f" on page {page}" if page else "")
                    + "\n"
                )
            blocks.append("\n")

    graph_edges = [c for c in ctx if c.get("source_type") == "graph"]
    if graph_edges and not any(k in ql for k in ("instrument", "where")):
        blocks.append("Extracted relationships:\n")
        for c in graph_edges[:8]:
            blocks.append(f"- `{c['entity']}` → `{c['relation']}` → `{c['target']}`\n")
        blocks.append("\n")

    low = [
        c for c in ctx if c.get("confidence") is not None and float(c["confidence"]) < 0.6
    ]
    # also scan the whole plant memory graph for low-confidence items
    graph_low: list[tuple[str, float]] = []
    for tag, data in graph.graph.nodes(data=True):
        conf = float(data.get("confidence", 1.0) or 1.0)
        if conf < 0.6:
            graph_low.append((tag, conf))
    for a, b, data in graph.graph.edges(data=True):
        conf = float(data.get("confidence", 1.0) or 1.0)
        if conf < 0.6:
            graph_low.append((f"{a} {data.get('relation','CONNECTED_TO')} {b}", conf))
    shown: list[tuple[str, float]] = []
    seen_labels = set()
    for lbl, conf in graph_low + [(c.get("entity") or c.get("text", ""), c["confidence"]) for c in low]:
        if lbl in seen_labels or not lbl:
            continue
        seen_labels.add(lbl)
        shown.append((lbl, float(conf)))
    shown.sort(key=lambda t: t[1])
    if shown and ("uncertain" in ql or "not sure" in ql or "confidence" in ql):
        blocks.append("\n**Uncertain extractions on this page:**\n")
        for lbl, conf in shown[:8]:
            blocks.append(f"- `{lbl}` confidence {conf:.0%}\n")
    elif low or graph_low:
        blocks.append(
            "\n_Note: some related extractions carry low confidence and are flagged "
            "as uncertain in the evidence panel._\n"
        )

    return blocks


def _retrieval_query(question: str, history: list[dict] | None) -> str:
    """Widen a bare follow-up with the last user turn that named a tag.

    "What instruments are on P-101?" followed by "and upstream of it?" retrieves
    nothing on its own; carrying the previous tag-bearing turn forward fixes it.
    """
    if _mention(question) or not history:
        return question
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        if _mention(turn.get("content", "")):
            return f"{turn['content']} {question}"
    return question


def _mention(query: str):
    m = re.search(r"\b([A-Z]{1,6}[- ]?\d{2,4}[A-Z0-9]?)\b", query.upper())
    if m:
        return re.sub(r" ", "-", m.group(1))
    return None