"""Answer generator — streaming chat completion across four modes.

Produces SSE event dicts:
`status` / `evidence` / `context` / `reasoning` / `token` / `done`.

Modes (`packages.prompts.modes`):

  plant    retrieval + the model's own engineering knowledge, kept apart
  general  no retrieval; the model answers from what it knows
  code     no retrieval; a coding assistant with a local, air-gapped posture
  think    a visible reasoning pass, then the answer

The `context` event reports the token budget the prompt was assembled
against (see `services/context.py`) so the UI can state what the model was
actually shown rather than implying it read everything retrieved.

Evidence is untrusted. Retrieved document text is sanitised (see
`services/safety.py`) before it reaches a prompt, because the retriever will
happily rank and paste a page that contains instructions aimed at the model.

When the configured chat model is unavailable (air-gap demo before pull),
a deterministic template answer is built directly from the evidence packet
so the demo still streams a credible, provable answer.
"""
from __future__ import annotations

import asyncio
import re

from sqlmodel import Session, select

from app.config import Settings
from app.services import audit, context as ctx, safety
from app.services.confidence import answer_confidence
from app.services.evidence_builder import build_evidence_packet, attach_document_meta
from app.services.graph_memory import GraphMemory
from app.services.hybrid_retriever import HybridRetriever
from app.services.ollama_gateway import OllamaGateway
from app.services.query_router import classify, choose_model, find_tags
from packages.prompts import prompt_version
from packages.prompts.modes import (
    MODE_CODE,
    MODE_GENERAL,
    MODE_PLANT,
    MODE_THINK,
    THINK_PLAN_PROMPT,
    normalize_mode,
    system_prompt,
)

UNKNOWN = "unknown"

# How much room each mode's answer gets. The global setting was 320 tokens —
# about 240 words — which is why every answer read as a stub no matter how
# much the question deserved. It stays as the floor so a deployment that
# raised it is still honoured, but each mode asks for what it actually needs:
# code has to fit a whole file, a reasoning scratchpad must stay short or it
# becomes the answer.
_ANSWER_TOKENS = {
    MODE_PLANT: 700,
    MODE_GENERAL: 800,
    MODE_CODE: 1200,
    MODE_THINK: 800,
}
_REASONING_TOKENS = 220

# Which modes read this project's memory at all. `think` is conditional: it
# retrieves when the question names a plant tag, so reasoning about P-101 is
# still grounded, but a general puzzle does not pay for a retrieval round
# trip that can only return noise.
_RETRIEVING_MODES = {MODE_PLANT}


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

    def _num_predict(self, mode: str) -> int:
        return max(self.settings.ollama_num_predict, _ANSWER_TOKENS.get(mode, 700))

    # ── main streaming entry point ────────────────────────────
    async def stream_chat(
        self,
        session: Session,
        project_id: int,
        question: str,
        top_k: int = 10,
        session_id: str = "web",
        history: list[dict] | None = None,
        mode: str = MODE_PLANT,
    ):
        mode = normalize_mode(mode)

        # ── policy, before anything else runs ─────────────────
        # Screened in front of the retriever and the model, not after: a
        # request to disclose the system prompt must not first cause a
        # retrieval, and a 1B model asked nicely to drop its rules drops them.
        verdict = safety.screen_request(question)
        if not verdict.allowed:
            audit.record_event(
                user_action="chat",
                model=UNKNOWN,
                session_id=session_id,
                result_status="refused:" + verdict.category,
            )
            async for ev in self._stream_text(verdict.message):
                yield ev
            yield {
                "type": "done",
                "message": verdict.message,
                "confidence": 0.0,
                "claims": [],
                "sources": [],
                "intent": "REFUSED",
                "model": UNKNOWN,
                "mode": mode,
                "refused": verdict.category,
                "grounded": False,
                "prompt_version": prompt_version("grounded_answer"),
            }
            return

        yield {"type": "status", "stage": "intent", "detail": "Understanding the question…"}
        route = classify(question)
        intent = route["intent"]
        tags = route["tags"]
        audit.record_event(
            user_action="chat",
            model=self.settings.ollama_chat_model,
            session_id=session_id,
            result_status=f"route:{intent}:{mode}",
        )

        # ── retrieval (plant, and think when a tag is named) ──
        packet: dict = {"answer_context": [], "confidence": 0.0}
        results: list = []
        retrieved = mode in _RETRIEVING_MODES or (mode == MODE_THINK and bool(tags))
        if retrieved:
            yield {"type": "status", "stage": "retrieving", "detail": "Searching plant memory…"}
            # A follow-up such as "and its upstream?" carries no tag of its
            # own; retrieval widens to the last user turn that did mention one.
            retrieval_query = _retrieval_query(question, history)
            results = await self.retriever.retrieve(
                session, project_id, retrieval_query, top_k=top_k
            )
            packet = build_evidence_packet(
                session, project_id, question, self.graph, results
            )
            packet["query_intent"] = intent
            packet = attach_document_meta(session, packet)

            # Retrieved text is data. An ingested drawing package can carry a
            # page written at the model rather than at a reader, and that page
            # is retrieved and pasted into the prompt like any other. Defang
            # it before it is either shown or sent.
            clean_rows, injection_hits = safety.sanitize_rows(
                packet.get("answer_context")
            )
            packet["answer_context"] = clean_rows
            if injection_hits:
                packet["sanitised_spans"] = injection_hits
                audit.record_event(
                    user_action="evidence_sanitised",
                    model=UNKNOWN,
                    session_id=session_id,
                    result_status=f"spans:{injection_hits}",
                )
                yield {
                    "type": "status",
                    "stage": "grounding",
                    "detail": (
                        f"Neutralised {injection_hits} instruction-like span"
                        f"{'s' if injection_hits != 1 else ''} in retrieved text"
                    ),
                }

            yield {"type": "status", "stage": "grounding", "detail": "Checking P&ID evidence…"}
            await asyncio.sleep(0.05)
            yield {"type": "evidence", "packet": packet}

        model = (
            choose_model(self.settings, intent, bool(tags))
            if retrieved
            else self.settings.ollama_chat_model
        )

        # A named tag with nothing behind it is the one case where the answer
        # must open by saying so. It no longer ENDS there: refusing to say
        # anything further left the user with a dead end when the general
        # engineering answer was both known and useful. The deterministic
        # "no evidence for X" lead is streamed first, then the model answers
        # the question from its own knowledge under a prompt that forbids
        # inventing anything plant-specific.
        grounded = True
        lead = ""
        if retrieved and tags and not _tags_present(packet, tags):
            grounded = False
            lead = self._no_evidence_message(session, project_id, tags) + "\n\n"
            async for ev in self._stream_text(lead):
                yield ev

        holder: dict = {"lead": lead}
        model_ready = await self.gateway.model_installed(self.settings.ollama_chat_model)

        if not model_ready:
            if not retrieved:
                # Nothing to fall back ON: the template path answers from an
                # evidence packet, and these modes have none.
                text = _NO_MODEL_MESSAGE.format(model=self.settings.ollama_chat_model)
                async for ev in self._stream_text(text):
                    yield ev
                holder["message"] = text
                holder["model"] = UNKNOWN
            else:
                async for ev in self._stream_template(packet, question, intent, holder):
                    yield ev
        else:
            # ── think: a visible reasoning pass first ─────────
            if mode == MODE_THINK:
                yield {"type": "status", "stage": "thinking", "detail": "Working it through…"}
                notes = ""
                async for ev in self._stream_reasoning(question, model, packet, history):
                    if ev["type"] == "reasoning":
                        notes += ev["text"]
                    yield ev
                holder["reasoning"] = notes.strip()

            yield {
                "type": "status",
                "stage": "answering",
                "detail": f"Writing the answer ({model})…",
            }
            async for ev in self._stream_llm(
                packet, question, model, intent, holder, history, mode, grounded
            ):
                yield ev

            # Small local models paraphrase evidence and can drop tags, so
            # the deterministic facts are appended as the verifiable body —
            # but only in plant mode, where there is evidence to verify
            # against. Appending "Verified from Plant Memory" to a coding
            # answer would be a lie with a reassuring heading on it.
            if mode == MODE_PLANT and grounded and not holder.get("skip_facts"):
                facts = self._facts_section(packet, question, intent)
                if facts:
                    async for ev in self._stream_text(facts):
                        yield ev
                    holder["message"] = holder.get("message", "") + facts

        message = lead + holder.get("message", "")
        llm_used = holder.get("model", model if model_ready else UNKNOWN)

        # ── output screening ──────────────────────────────────
        # Layers 1 and 2 both missed if this fires, which is exactly why it
        # exists: an injection that survives into the answer is the one that
        # would otherwise reach the user.
        out_verdict = safety.screen_output(message)
        if not out_verdict.allowed:
            audit.record_event(
                user_action="answer",
                model=llm_used,
                session_id=session_id,
                result_status="blocked:" + out_verdict.category,
            )
            yield {"type": "status", "stage": "blocked", "detail": out_verdict.reason}
            message = out_verdict.message
            yield {"type": "replace", "text": message}

        # ── finalize ───────────────────────────────────────────
        claims, sources = self._shape_claims_and_sources(packet)
        confidence = (
            answer_confidence(
                [
                    c["confidence"]
                    for c in packet.get("answer_context", [])
                    if c.get("confidence")
                ]
            )
            if retrieved
            else 0.0
        )
        audit.record_event(
            user_action="answer",
            model=llm_used,
            session_id=session_id,
            retrieval_count=len(results),
            result_status="ok" if message else "empty",
        )
        yield {
            "type": "done",
            "message": message,
            "confidence": round(confidence, 3),
            "claims": claims,
            "sources": sources,
            "intent": intent,
            "model": llm_used,
            "mode": mode,
            "grounded": grounded and retrieved,
            "retrieved": retrieved,
            "reasoning": holder.get("reasoning", ""),
            "context": holder.get("context"),
            "prompt_version": prompt_version("plant_answer"),
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
        mode: str = MODE_PLANT,
        grounded: bool = True,
    ):
        # The prompt is assembled against this model's own context window
        # rather than assumed to fit. `options` carries an explicit num_ctx,
        # so what the budget reserved is what the server actually allocates —
        # otherwise Ollama's default window silently drops the front of the
        # prompt, which is where the rules and the evidence are.
        rows = packet.get("answer_context") or []
        # The scratchpad rides in front of the question, not in place of the
        # evidence header — a think-mode turn about P-101 has both, and
        # labelling retrieved graph edges as "your reasoning notes" would
        # invite the model to treat plant facts as its own speculation.
        preamble = ""
        if mode == MODE_THINK and result.get("reasoning"):
            preamble = f"Your reasoning notes:\n{result['reasoning']}"

        messages, options, report = ctx.assemble(
            model=model,
            num_predict=self._num_predict(mode),
            system=system_prompt(mode, grounded=grounded),
            question=question,
            answer_context=rows,
            history=history,
            include_evidence=bool(rows),
            preamble=preamble,
        )
        result["context"] = report.as_dict()
        # Emitted before the first token so the trace can state what the
        # model was given at the moment it was given it.
        yield {"type": "context", "report": report.as_dict()}
        parts: list[str] = []
        try:
            async for token in self.gateway.chat_stream(messages, model, options):
                parts.append(token)
                yield {"type": "token", "text": token}
        except Exception as exc:
            if not rows:
                # No evidence to fall back on — report the failure rather
                # than silently producing an empty turn.
                text = f"The model failed partway through: {exc}"
                if not parts:
                    yield {"type": "token", "text": text}
                    parts.append(text)
                result["message"] = "".join(parts)
                result.setdefault("model", model)
                return
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

    # ── think: the visible reasoning pass ─────────────────────
    async def _stream_reasoning(
        self,
        question: str,
        model: str,
        packet: dict,
        history: list[dict] | None,
    ):
        """Stream a short scratchpad as `reasoning` events.

        Kept deliberately small (`_REASONING_TOKENS`): on a CPU this is a
        second full generation, and an unbounded one doubles the wait for
        every answer. The cap also stops the scratchpad turning into the
        answer, which a small model will otherwise happily do.
        """
        messages, options, _report = ctx.assemble(
            model=model,
            num_predict=_REASONING_TOKENS,
            system=THINK_PLAN_PROMPT,
            question=question,
            answer_context=packet.get("answer_context") or [],
            history=history,
            evidence_header="What this plant's memory holds on it:",
        )
        options["temperature"] = 0.3
        try:
            async for token in self.gateway.chat_stream(messages, model, options):
                yield {"type": "reasoning", "text": token}
        except Exception:
            # Reasoning is an aid, not the deliverable. If it fails the
            # answer pass still runs, without notes.
            yield {"type": "status", "detail": "Reasoning pass failed; answering directly."}

    async def _stream_text(self, text: str):
        """Stream a server-authored string as tokens, so it renders live."""
        for i in range(0, len(text), 48):
            yield {"type": "token", "text": text[i : i + 48]}
            await asyncio.sleep(0.008)

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
                f"**No evidence for {wanted} in this project** — nothing has "
                "been ingested here yet, so anything below is general "
                "engineering knowledge rather than this plant's design."
            )
        return (
            f"**No evidence for {wanted} in this project.** Everything below "
            "is general engineering knowledge, not this plant's design.\n\n"
            "Tags this project does contain: "
            + ", ".join(known)
            + ("…" if len(known) == 24 else "")
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
        async for ev in self._stream_text(text):
            yield ev
        result["message"] = text
        result["model"] = UNKNOWN

    # ── structured shape (README section 27) ─────────────────
    def _shape_claims_and_sources(self, packet) -> tuple[list[dict], list[dict]]:
        claims: list[dict] = []
        sources: list[dict] = []
        for item in (packet.get("answer_context") or [])[:12]:
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


_NO_MODEL_MESSAGE = (
    "The local model `{model}` is not installed, and this mode answers from "
    "the model rather than from retrieved documents — so there is nothing to "
    "fall back to.\n\n"
    "Pull it on this workstation (`ollama pull {model}`), or switch to "
    "**Plant** mode, which can still answer deterministically from the "
    "extracted plant memory."
)


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
