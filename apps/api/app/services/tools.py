"""Typed tool registry (README §4.8, LLM06 "Excessive Agency").

Every action the agent can take is declared here with an explicit input
schema and a permission. The agent cannot call anything that is not in this
registry, and there is no shell, no `eval`, and no network tool — an agent
whose action space is a closed list is the only kind that can be reasoned
about in a safety-critical deployment.

Each tool returns a `ToolResult`, never a bare value, so a caller always sees
whether the call succeeded, what it produced, and what evidence it touched.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from sqlmodel import Session, select

from app.services import audit
from app.services.calc_engine import (
    CalculationError,
    calculate,
    list_operations,
)
from app.services.renderers import (
    Citation,
    Section,
    render_docx,
    render_pdf,
    render_xlsx,
)


@dataclass
class ToolResult:
    ok: bool
    tool: str
    output: Any = None
    error: str = ""
    citations: list[dict] = field(default_factory=list)
    artifact: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "output": self.output,
            "error": self.error,
            "citations": self.citations,
            "artifact": self.artifact,
        }


@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    permission: str  # read | compute | write
    run: Callable[..., Awaitable[ToolResult]]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema,
            "permission": self.permission,
        }


class ToolContext:
    """Everything a tool is allowed to touch, passed explicitly.

    Tools receive this rather than reaching for globals, so the blast radius
    of any one tool is visible at the call site.
    """

    def __init__(self, session: Session, state, project_id: int, out_dir: Path,
                 clearance: str = "internal"):
        self.session = session
        self.state = state
        self.project_id = project_id
        self.out_dir = out_dir
        self.clearance = clearance


# ── retrieve ──────────────────────────────────────────────────
async def _retrieve(ctx: ToolContext, query: str, top_k: int = 8) -> ToolResult:
    from app.services.evidence_builder import (
        attach_document_meta,
        build_evidence_packet,
    )

    if not str(query or "").strip():
        return ToolResult(False, "retrieve", error="query must not be empty")

    ctx.state.graph.rebuild(ctx.session, ctx.project_id)
    results = await ctx.state.retriever.retrieve(
        ctx.session, ctx.project_id, query, top_k=int(top_k)
    )
    packet = build_evidence_packet(
        ctx.session, ctx.project_id, query, ctx.state.graph, results
    )
    packet = attach_document_meta(ctx.session, packet)

    citations = [
        {
            "label": c.get("entity") or (c.get("text") or "")[:60],
            "document": c.get("document") or "",
            "page": c.get("page"),
            "bbox": c.get("bbox"),
            "source_type": c.get("source_type", "pid"),
        }
        for c in packet["answer_context"][:12]
    ]
    audit.record_event(
        user_action="tool:retrieve", tool_name="retrieve",
        retrieval_count=len(results), result_status="ok",
    )
    return ToolResult(
        ok=True, tool="retrieve",
        output={
            "hits": len(results),
            "context": packet["answer_context"][:12],
            "retrieved_from": packet.get("retrieved_from", ""),
        },
        citations=citations,
    )


# ── calculate ─────────────────────────────────────────────────
async def _calculate(
    ctx: ToolContext, operation: str, inputs: dict, output_unit: str = ""
) -> ToolResult:
    try:
        result = calculate(operation, inputs or {}, output_unit or None)
    except CalculationError as exc:
        # A refused calculation is a correct outcome, not a crash: the agent
        # is told why so it can fix the request rather than invent a number.
        audit.record_event(
            user_action="tool:calculate", tool_name="calculate",
            result_status="refused",
        )
        return ToolResult(False, "calculate", error=str(exc))

    audit.record_event(
        user_action="tool:calculate", tool_name="calculate", result_status="ok",
    )
    return ToolResult(
        ok=True, tool="calculate", output=result.as_dict(),
        citations=[
            {
                "label": f"{p['input']} = {p['value']} {p['unit']}".strip(),
                "document": p.get("source", ""),
                "source_type": "calculation",
            }
            for p in result.provenance
        ],
    )


# ── render_docx ───────────────────────────────────────────────
def _as_sections(raw: list[dict]) -> list[Section]:
    sections: list[Section] = []
    for item in raw or []:
        sections.append(
            Section(
                heading=str(item.get("heading", "Section")),
                body=str(item.get("body", "") or ""),
                bullets=[str(b) for b in (item.get("bullets") or [])],
                table=item.get("table"),
                citations=[
                    Citation(
                        label=str(c.get("label", "") or ""),
                        document=str(c.get("document", "") or ""),
                        page=c.get("page"),
                        bbox=c.get("bbox"),
                        source_type=str(c.get("source_type", "pid")),
                    )
                    for c in (item.get("citations") or [])
                ],
            )
        )
    return sections


async def _render_docx(
    ctx: ToolContext, title: str, sections: list[dict], subtitle: str = ""
) -> ToolResult:
    if not sections:
        return ToolResult(False, "render_docx", error="sections must not be empty")
    artifact = render_docx(
        ctx.out_dir,
        title=str(title or "Meshcore deliverable"),
        sections=_as_sections(sections),
        subtitle=subtitle,
        metadata={"project_id": ctx.project_id},
    )
    audit.record_event(
        user_action="tool:render_docx", tool_name="render_docx", result_status="ok",
    )
    return ToolResult(
        ok=True, tool="render_docx",
        output={"file": artifact.name, "citations": artifact.citations},
        artifact=artifact.as_dict(),
    )


# ── render_pdf ────────────────────────────────────────────────
# Same content contract as render_docx on purpose: the agent decides the
# format from the request and swaps the tool, without reshaping the sections.
async def _render_pdf(
    ctx: ToolContext, title: str, sections: list[dict], subtitle: str = ""
) -> ToolResult:
    if not sections:
        return ToolResult(False, "render_pdf", error="sections must not be empty")
    artifact = render_pdf(
        ctx.out_dir,
        title=str(title or "Meshcore deliverable"),
        sections=_as_sections(sections),
        subtitle=subtitle,
        metadata={"project_id": ctx.project_id},
    )
    audit.record_event(
        user_action="tool:render_pdf", tool_name="render_pdf", result_status="ok",
    )
    return ToolResult(
        ok=True, tool="render_pdf",
        output={"file": artifact.name, "citations": artifact.citations},
        artifact=artifact.as_dict(),
    )


# ── render_xlsx ───────────────────────────────────────────────
async def _render_xlsx(
    ctx: ToolContext,
    title: str,
    columns: list[str],
    rows: list[list],
    citations: Optional[list[dict]] = None,
) -> ToolResult:
    if not columns:
        return ToolResult(False, "render_xlsx", error="columns must not be empty")
    artifact = render_xlsx(
        ctx.out_dir,
        title=str(title or "Meshcore table"),
        columns=[str(c) for c in columns],
        rows=rows or [],
        citations=[
            Citation(
                label=str(c.get("label", "") or ""),
                document=str(c.get("document", "") or ""),
                page=c.get("page"),
                source_type=str(c.get("source_type", "pid")),
            )
            for c in (citations or [])
        ],
        metadata={"project_id": ctx.project_id},
    )
    audit.record_event(
        user_action="tool:render_xlsx", tool_name="render_xlsx", result_status="ok",
    )
    return ToolResult(
        ok=True, tool="render_xlsx",
        output={"file": artifact.name, "rows": len(rows or [])},
        artifact=artifact.as_dict(),
    )


# ── list_entities (tabular source for trackers) ───────────────
async def _list_entities(
    ctx: ToolContext, entity_type: str = "", page: Optional[int] = None
) -> ToolResult:
    from app.models import Document, DocumentPage, Entity

    stmt = select(Entity).where(Entity.project_id == ctx.project_id)
    if entity_type:
        stmt = stmt.where(Entity.entity_type == entity_type)
    rows = ctx.session.exec(stmt.order_by(Entity.canonical_tag)).all()

    page_numbers = {
        p.id: p.page_number
        for p in ctx.session.exec(select(DocumentPage)).all()
    }
    doc_names = {d.id: d.name for d in ctx.session.exec(select(Document)).all()}

    out = []
    for e in rows:
        page_no = page_numbers.get(e.page_id)
        if page is not None and page_no != page:
            continue
        try:
            meta = json.loads(e.metadata_json or "{}")
        except ValueError:
            meta = {}
        out.append({
            "tag": e.canonical_tag,
            "type": e.entity_type,
            "label": e.label,
            "confidence": round(e.confidence, 3),
            "document": doc_names.get(e.document_id, ""),
            "page": page_no,
            "bbox": [e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
            "needs_review": bool(meta.get("needs_review")),
        })
    audit.record_event(
        user_action="tool:list_entities", tool_name="list_entities",
        retrieval_count=len(out), result_status="ok",
    )
    return ToolResult(ok=True, tool="list_entities", output={"entities": out})



# ── draft (general, non-plant content) ────────────────────────
# Everything above answers from plant memory. This one does not: it asks the
# language model to compose content from its own knowledge, for requests that
# have no evidence in the project at all ("a spreadsheet of the top vision
# models"). That is a genuinely different epistemic status from a grounded
# answer, so output from this tool is labelled UNVERIFIED everywhere it
# surfaces — in the stream, on the rendered page and in the provenance
# sidecar. It is never used for engineering numbers: `calculate` stays the
# only path to those, and it has no access to this.
_DRAFT_TABLE_SYSTEM = (
    "You produce compact factual tables as JSON.\n"
    "Reply with ONLY a JSON object, no prose and no markdown fence.\n"
    'Shape: {"title": str, "columns": [str], "rows": [[cell, cell]]}\n'
    "EVERY row must be an ARRAY with exactly one cell per column, in the "
    "same order as the columns. Never write a row as a bare string.\n"
    "Use at most 5 columns and at most 20 rows. Fill every cell; write "
    '"n/a" if a value is genuinely unknown.\n'
    "Example of the required shape:\n"
    '{"title": "Example", "columns": ["Name", "Year", "Score"], '
    '"rows": [["Alpha", "2021", "88"], ["Beta", "2023", "91"]]}'
)
_DRAFT_DOC_SYSTEM = (
    "You produce short structured reports as JSON.\n"
    "Reply with ONLY a JSON object, no prose and no markdown fence.\n"
    'Shape: {"title": str, "sections": [{"heading": str, "body": str, '
    '"bullets": [str]}]}\n'
    "At most 6 sections. Each body is 2-4 sentences."
)


def _parse_json_object(raw: str) -> Optional[dict]:
    """Pull one JSON object out of a model reply, repairing a truncated tail.

    Two things reliably go wrong with a small local model here. It fences its
    JSON however firmly it is told not to, so the braces are located rather
    than trusted. And it runs out of token budget mid-structure, which used to
    throw away a perfectly good table because its last row was half-written.
    A truncated table is still a table: the complete rows are kept and the
    partial one is dropped.
    """
    text = (raw or "").strip()
    if "```" in text:
        # Take the fenced block if there is one, else strip stray fences.
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    start = text.find("{")
    if start < 0:
        return None
    body = text[start:]

    end = body.rfind("}")
    if end > 0:
        try:
            parsed = json.loads(body[: end + 1])
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass  # truncated or malformed — fall through to repair

    return _repair_json_object(body)


def _repair_json_object(body: str) -> Optional[dict]:
    """Close an unterminated JSON object by trimming to the last safe point.

    Walks the text tracking string state and nesting depth, remembers the
    position after each element that closed cleanly at depth 2 (a completed
    row or section), truncates there and shuts the structure.
    """
    depth = 0
    in_string = False
    escaped = False
    last_safe = -1

    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 2:
                last_safe = i + 1   # a complete row/section just closed
        elif ch == "," and depth == 2:
            last_safe = i           # element boundary, comma excluded

    if last_safe <= 0:
        return None

    trimmed = body[:last_safe].rstrip().rstrip(",")
    # Re-count what is still open, then close it in the right order.
    depth = 0
    in_string = False
    escaped = False
    stack: list[str] = []
    for ch in trimmed:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()

    candidate = trimmed + "".join(reversed(stack))
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _draft(ctx: ToolContext, request: str, shape: str = "table") -> ToolResult:
    gateway = getattr(ctx.state, "gateway", None)
    if gateway is None:
        return ToolResult(False, "draft", error="No model gateway configured")
    if not await gateway.is_available():
        return ToolResult(
            False, "draft",
            error="Drafting needs a local model. Start Ollama and pull a chat model.",
        )

    settings = getattr(ctx.state, "settings", None)
    model = getattr(settings, "ollama_chat_model", "") or "qwen3:4b"
    system = _DRAFT_DOC_SYSTEM if shape == "document" else _DRAFT_TABLE_SYSTEM

    raw = await gateway.complete(
        prompt=str(request or "").strip(),
        model=model,
        system=system,
        temperature=0.3,
        # Chat answers are capped short deliberately; a JSON table is not a
        # chat answer, and at the default cap it arrives truncated every time.
        # 900 fits a 20-row table comfortably. Higher just buys rows that the
        # 25-row cap discards anyway, at roughly a second each on CPU.
        num_predict=900,
    )
    parsed = _parse_json_object(raw)
    if not parsed:
        return ToolResult(
            False, "draft", error="Model did not return usable JSON for this request"
        )

    audit.record_event(
        user_action="tool:draft", tool_name="draft",
        model=model, result_status="ok:unverified",
    )
    parsed["_unverified"] = True
    return ToolResult(
        ok=True, tool="draft", output=parsed,
        citations=[{
            "label": f"Model knowledge ({model}) — UNVERIFIED, not plant evidence",
            "document": "", "source_type": "model",
        }],
    )


REGISTRY: dict[str, Tool] = {
    "retrieve": Tool(
        name="retrieve",
        description="Search plant memory and documents; returns cited evidence.",
        schema={"query": "string", "top_k": "integer (optional, default 8)"},
        permission="read",
        run=_retrieve,
    ),
    "list_entities": Tool(
        name="list_entities",
        description=(
            "List extracted entities, optionally filtered by type "
            "(equipment|instrument|valve|process_line) or page number."
        ),
        schema={"entity_type": "string (optional)", "page": "integer (optional)"},
        permission="read",
        run=_list_entities,
    ),
    "draft": Tool(
        name="draft",
        description=(
            "Compose general content from model knowledge when the project "
            "holds no evidence for the request. Output is UNVERIFIED and is "
            "labelled as such; never used for engineering numbers."
        ),
        schema={"request": "string", "shape": "'table' | 'document'"},
        permission="compute",
        run=_draft,
    ),
    "calculate": Tool(
        name="calculate",
        description=(
            "Run one whitelisted engineering calculation. The model supplies a "
            "request; the engine produces the number. Operations: "
            + ", ".join(o["operation"] for o in list_operations())
        ),
        schema={
            "operation": "string",
            "inputs": "object of {name: {value, unit, source}}",
            "output_unit": "string (optional)",
        },
        permission="compute",
        run=_calculate,
    ),
    "render_docx": Tool(
        name="render_docx",
        description="Render a cited DOCX deliverable with a provenance sidecar.",
        schema={
            "title": "string",
            "subtitle": "string (optional)",
            "sections": "[{heading, body, bullets[], table{columns,rows}, citations[]}]",
        },
        permission="write",
        run=_render_docx,
    ),
    "render_pdf": Tool(
        name="render_pdf",
        description="Render a cited PDF deliverable with a provenance sidecar.",
        schema={
            "title": "string",
            "subtitle": "string (optional)",
            "sections": "[{heading, body, bullets[], table{columns,rows}, citations[]}]",
        },
        permission="write",
        run=_render_pdf,
    ),
    "render_xlsx": Tool(
        name="render_xlsx",
        description="Render a tabular XLSX deliverable (tracker, instrument list).",
        schema={
            "title": "string",
            "columns": "[string]",
            "rows": "[[value]]",
            "citations": "[{label, document, page}] (optional)",
        },
        permission="write",
        run=_render_xlsx,
    ),
}


def describe_tools() -> list[dict]:
    return [t.as_dict() for t in REGISTRY.values()]


async def invoke(ctx: ToolContext, name: str, arguments: dict) -> ToolResult:
    """Call one registered tool. Unknown names are refused, not guessed at."""
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolResult(
            False, name,
            error=f"Unknown tool {name!r}. Available: {sorted(REGISTRY)}",
        )
    try:
        return await tool.run(ctx, **(arguments or {}))
    except TypeError as exc:
        # Wrong arguments are a schema violation, reported as such.
        return ToolResult(False, name, error=f"Invalid arguments for {name}: {exc}")
    except Exception as exc:
        audit.record_event(
            user_action=f"tool:{name}", tool_name=name, result_status="failed",
        )
        return ToolResult(False, name, error=f"{type(exc).__name__}: {exc}")
