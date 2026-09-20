"""Bounded agent loop (README §4.8).

An unbounded ReAct loop in a refinery is a liability, so this is a state
machine with hard budgets rather than "keep going until the model stops":

    INTAKE → PLAN → POLICY → EXECUTE → OBSERVE ─┐
                      ▲                          │ goal unmet, budget remains
                      └──────────────────────────┘
                                 ↓ goal met / budget spent
                            VERIFY → DELIVER

Budgets, quotable as-is: **3 replans, 12 tool calls, 180 s wall clock.**
Being able to state those is the maturity signal; enforcing them is what
makes the statement true, so `AgentBudget` is checked at every transition.

Planning is deliberately deterministic. A small local model is unreliable at
emitting a well-formed plan, and a task plan that varies run to run cannot be
audited — so the task is classified by rule and mapped to a plan template.
The model writes prose; it never picks the numbers or the tools.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from sqlmodel import Session

from app.services import audit, tools
from app.services.calc_engine import list_operations
from app.services.tools import ToolContext, ToolResult

MAX_REPLANS = 3
MAX_TOOL_CALLS = 12
WALL_CLOCK_SECONDS = 180


@dataclass
class AgentBudget:
    """Hard limits. Exhausting one ends the run; it never silently continues."""

    max_replans: int = MAX_REPLANS
    max_tool_calls: int = MAX_TOOL_CALLS
    wall_clock_seconds: int = WALL_CLOCK_SECONDS
    started_at: float = field(default_factory=time.perf_counter)
    replans: int = 0
    tool_calls: int = 0

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    def exhausted(self) -> Optional[str]:
        if self.tool_calls >= self.max_tool_calls:
            return f"tool-call budget spent ({self.max_tool_calls})"
        if self.replans >= self.max_replans:
            return f"replan budget spent ({self.max_replans})"
        if self.elapsed >= self.wall_clock_seconds:
            return f"wall-clock budget spent ({self.wall_clock_seconds}s)"
        return None

    def as_dict(self) -> dict:
        return {
            "tool_calls": self.tool_calls,
            "max_tool_calls": self.max_tool_calls,
            "replans": self.replans,
            "max_replans": self.max_replans,
            "elapsed_s": round(self.elapsed, 2),
            "wall_clock_seconds": self.wall_clock_seconds,
        }


@dataclass
class PlannedCall:
    tool: str
    arguments: dict
    why: str


# ── INTAKE: deterministic task classification ─────────────────
TASK_MOC = "MOC_NOTE"
TASK_TRACKER = "TRACKER"
TASK_CALC = "CALCULATION"
TASK_ANSWER = "GROUNDED_ANSWER"
# A file about something the project holds no evidence for. Kept as its own
# task rather than folded into TRACKER because the two differ in the only way
# that matters here: a tracker's rows are cited plant data, these are not.
TASK_GENERAL_DOC = "GENERAL_DOCUMENT"
# A file about the plant that is not a tracker, an MOC note or a calculation
# record — "a PDF report on P-101". Grounded like a tracker, prose like an
# MOC note, and previously not covered by either.
TASK_GROUNDED_DOC = "GROUNDED_DOCUMENT"

_TAG_RE = re.compile(r"\b([A-Z]{1,5}[- ]?\d{2,5}[A-Z]?)\b")

# Asking for a FILE — "generate an excel of…", "write a doc about…".
_ARTIFACT_RE = re.compile(
    r"\b(excel|xlsx|spreadsheet|csv|sheet|docx|word document|pdf|report|"
    r"write.?up|document)\b",
    re.I,
)
# Naming something in the plant. A request that asks for a file AND names
# plant subject matter is a tracker built from cited evidence; one that asks
# for a file about anything else has no evidence in the project at all.
#
# A bare tag counts as plant subject matter. "Write a report on P-101" names
# nothing from the keyword list, and without the tag pattern it took the
# general path — producing a model-invented report about a pump this project
# holds real drawings of, which is the worst of both available outcomes.
# Plurals are explicit: `\binstrument\b` does not match "instruments", which
# is the form every real request uses ("an excel of all instruments"). That
# single missing `s?` routed plant requests down the ungrounded path.
_PLANT_SUBJECT_RE = re.compile(
    r"\b(p&?id|drawings?|instruments?|valves?|pumps?|vessels?|equipment|"
    r"lines?|tags?|loops?|entity|entities|plant|units?|exchangers?|"
    r"reactors?|relief|process)\b"
    r"|\b[A-Z]{1,5}-\d{2,5}[A-Z]?\b",
    re.I,
)

# ── FORMAT: which file the sentence is asking for ─────────────
# There is no format picker in the UI and there should not be one: the user
# already said "excel" or "pdf" in the sentence, and making them say it twice
# in a dropdown is the interaction this replaces.
FORMAT_XLSX = "xlsx"
FORMAT_DOCX = "docx"
FORMAT_PDF = "pdf"

_FORMAT_RULES = (
    (re.compile(r"\b(excel|xlsx|spreadsheet|csv|workbook)\b", re.I), FORMAT_XLSX),
    (re.compile(r"\bpdf\b", re.I), FORMAT_PDF),
    (re.compile(r"\b(docx|word)\b", re.I), FORMAT_DOCX),
)

# Shape words, used only when no format was named: a "tracker" or a "list"
# is tabular and belongs in a sheet; a "note" or a "report" is prose.
_TABULAR_SHAPE_RE = re.compile(
    r"\b(sheet|table|tabular|tracker|register|inventory|matrix|schedule|"
    r"list of|all instruments|all valves|all equipment)\b",
    re.I,
)

_RENDER_TOOL = {
    FORMAT_XLSX: "render_xlsx",
    FORMAT_DOCX: "render_docx",
    FORMAT_PDF: "render_pdf",
}


def detect_format(prompt: str, default: str = FORMAT_DOCX) -> str:
    """Which file format the request asks for.

    Falls back to shape — tabular subject matter becomes a spreadsheet — and
    only then to `default`. Tabular output is never silently turned into a
    PDF: a 400-row instrument register is a spreadsheet, and printing it is
    a decision the user makes afterwards.
    """
    text = prompt or ""
    for pattern, fmt in _FORMAT_RULES:
        if pattern.search(text):
            return fmt
    if _TABULAR_SHAPE_RE.search(text):
        return FORMAT_XLSX
    return default


def render_tool_for(fmt: str) -> str:
    """The registered renderer that produces `fmt`."""
    return _RENDER_TOOL.get(fmt, "render_docx")


_TASK_RULES = (
    (re.compile(r"\b(moc|management of change|change note|change request)\b", re.I), TASK_MOC),
    # "every valve", "all instruments" — an enumeration of one entity type is
    # a tracker whatever noun the user reached for, so the quantifier forms
    # are matched as well as the explicit words.
    (re.compile(r"\b(tracker|list of|compile|inventory|register|schedule of|table of)\b"
                r"|\b(all|every|each)\s+(?:the\s+)?"
                r"(instrument|valve|pump|equipment|vessel|line|tag|entit|loop)\w*\b", re.I), TASK_TRACKER),
    (re.compile(r"\b(pressure drop|calculate|compute|velocity|reynolds|sizing|relief|power)\b", re.I), TASK_CALC),
)


def classify_task(prompt: str) -> str:
    text = prompt or ""
    wants_file = bool(_ARTIFACT_RE.search(text))
    about_plant = bool(_PLANT_SUBJECT_RE.search(text))

    # A file request with no plant subject in it cannot be answered from plant
    # memory, so it takes the general path instead of returning an empty
    # tracker. This is checked first: "make a spreadsheet of the top vision
    # models" matches the tracker rule on "table of"/"list of" otherwise.
    if wants_file and not about_plant:
        return TASK_GENERAL_DOC
    for pattern, task in _TASK_RULES:
        if pattern.search(text):
            return task
    # Asked for a file about the plant, but not for a tracker, an MOC note or
    # a calculation — "a PDF report on P-101". This used to fall through to
    # TASK_ANSWER, whose plan is a bare `retrieve`: the user asked for a file
    # and got a retrieval with nothing to download. It is its own task because
    # the content is grounded, unlike TASK_GENERAL_DOC.
    if wants_file:
        return TASK_GROUNDED_DOC
    return TASK_ANSWER


def wants_spreadsheet(prompt: str) -> bool:
    """True when the asked-for artefact is tabular rather than prose."""
    return bool(
        re.search(r"\b(excel|xlsx|spreadsheet|csv|sheet|table|tracker|list)\b",
                  prompt or "", re.I)
    )


def find_tag(prompt: str) -> str:
    m = _TAG_RE.search((prompt or "").upper())
    return re.sub(r" ", "-", m.group(1)) if m else ""


_TYPE_WORDS = {
    "instrument": "instrument",
    "instruments": "instrument",
    "valve": "valve",
    "valves": "valve",
    "equipment": "equipment",
    "line": "process_line",
    "lines": "process_line",
    "pipe": "process_line",
}


def _wanted_type(prompt: str) -> str:
    low = (prompt or "").lower()
    for word, etype in _TYPE_WORDS.items():
        if re.search(rf"\b{word}\b", low):
            return etype
    return ""


def _wanted_page(prompt: str) -> Optional[int]:
    m = re.search(r"\b(?:sheet|page)\s*(\d{1,3})\b", prompt or "", re.I)
    return int(m.group(1)) if m else None


# ── PLAN: task → ordered typed tool calls ─────────────────────
# Each task has a natural default format, which an explicitly named one in
# the request overrides. A tracker is tabular unless the user asked for a
# PDF; an MOC note is prose unless they asked for a spreadsheet.
_DEFAULT_FORMAT_BY_TASK = {
    TASK_MOC: FORMAT_DOCX,
    TASK_TRACKER: FORMAT_XLSX,
    TASK_CALC: FORMAT_DOCX,
    TASK_GENERAL_DOC: FORMAT_DOCX,
    TASK_GROUNDED_DOC: FORMAT_DOCX,
}

# Which deferred-argument builder shapes the content for a given format.
# Prose renderers take `sections`, the spreadsheet takes `columns`/`rows`,
# so the pairing is part of the plan rather than guessed at fill time.
_DEFER_PROSE = {"general_doc", "moc", "calc_note", "tracker_doc"}


def build_plan(
    prompt: str, task: str, fmt: str = "", query: str = ""
) -> list[PlannedCall]:
    """Ordered typed tool calls for one task.

    `query` is what retrieval searches for and defaults to `prompt`. They
    differ for a bare follow-up: "now make that a PDF" retrieves nothing on
    its own words, so the caller passes the subject resolved from the thread
    while `prompt` — which titles the file and quotes the request back —
    stays the sentence the user actually typed.
    """
    tag = find_tag(query or prompt)
    fmt = fmt or detect_format(
        prompt, default=_DEFAULT_FORMAT_BY_TASK.get(task, FORMAT_DOCX)
    )
    search = (query or prompt).strip() or prompt
    tabular = fmt == FORMAT_XLSX
    renderer = render_tool_for(fmt)

    if task == TASK_MOC:
        return [
            PlannedCall("retrieve", {"query": search, "top_k": 10},
                        "Gather cited evidence for the change"),
            PlannedCall("retrieve", {"query": f"{tag} connections instruments valves".strip(),
                                     "top_k": 8},
                        f"Establish what {tag or 'the item'} is connected to"),
            PlannedCall(renderer, {"_defer": "moc"},
                        f"Render the MOC note with citations ({fmt.upper()})"),
        ]
    if task == TASK_GENERAL_DOC:
        return [
            PlannedCall("draft",
                        {"request": prompt,
                         "shape": "table" if tabular else "document"},
                        "Compose the content (model knowledge — UNVERIFIED)"),
            PlannedCall(renderer,
                        {"_defer": "general_table" if tabular else "general_doc"},
                        f"Render the {fmt.upper()} for download"),
        ]
    if task == TASK_GROUNDED_DOC:
        plan = [
            PlannedCall("retrieve", {"query": search, "top_k": 12},
                        "Retrieve the cited evidence for this subject"),
        ]
        if tabular:
            plan.append(
                PlannedCall("list_entities",
                            {"entity_type": _wanted_type(prompt),
                             "page": _wanted_page(prompt)},
                            "Collect the rows for the sheet"))
            plan.append(
                PlannedCall(renderer, {"_defer": "tracker"},
                            "Render the sheet"))
        else:
            plan.append(
                PlannedCall(renderer, {"_defer": "grounded_doc"},
                            f"Render the {fmt.upper()} from the evidence"))
        return plan
    if task == TASK_TRACKER:
        return [
            PlannedCall("list_entities",
                        {"entity_type": _wanted_type(prompt), "page": _wanted_page(prompt)},
                        "Collect the rows for the tracker"),
            PlannedCall(renderer,
                        {"_defer": "tracker" if tabular else "tracker_doc"},
                        f"Render the tracker as {fmt.upper()}"),
        ]
    if task == TASK_CALC:
        return [
            PlannedCall("retrieve", {"query": search, "top_k": 8},
                        "Find line size, service and stream data"),
            PlannedCall("calculate", {"_defer": "calc"},
                        "Run the whitelisted calculation"),
            PlannedCall(renderer, {"_defer": "calc_note"},
                        f"Render the calculation record ({fmt.upper()})"),
        ]
    return [
        PlannedCall("retrieve", {"query": search, "top_k": 10},
                    "Retrieve grounded evidence"),
    ]


# ── POLICY ────────────────────────────────────────────────────
PERMISSIONS_BY_CLEARANCE = {
    "operator": {"read"},
    "engineer": {"read", "compute"},
    "senior_engineer": {"read", "compute", "write"},
    "internal": {"read", "compute", "write"},
}


def policy_decision(call: PlannedCall, clearance: str) -> tuple[str, str]:
    """allow | deny — evaluated before every tool call, not once at the start."""
    tool = tools.REGISTRY.get(call.tool)
    if tool is None:
        return "deny", f"{call.tool} is not a registered tool"
    allowed = PERMISSIONS_BY_CLEARANCE.get(clearance, {"read"})
    if tool.permission not in allowed:
        return "deny", (
            f"clearance '{clearance}' does not grant '{tool.permission}' "
            f"needed by {call.tool}"
        )
    return "allow", "permitted"


# ── deferred argument construction ────────────────────────────
def _moc_sections(prompt: str, tag: str, evidence: list[dict]) -> list[dict]:
    cites = [
        {
            "label": c.get("entity") or (c.get("text") or "")[:50],
            "document": c.get("document") or "",
            "page": c.get("page"),
            "bbox": c.get("bbox"),
            "source_type": c.get("source_type", "pid"),
        }
        for c in evidence[:8]
    ]
    connections = [
        f"{c.get('entity')} → {c.get('relation')} → {c.get('target')}"
        for c in evidence
        if c.get("source_type") == "graph" and c.get("entity") and c.get("target")
    ][:10]
    return [
        {
            "heading": "1. Change description",
            "body": prompt.strip(),
            "citations": cites[:3],
        },
        {
            "heading": "2. Affected item",
            "body": (
                f"This change concerns {tag}. The extracted plant memory records "
                f"the following connections for it."
                if tag else
                "The affected item could not be resolved to a single plant tag; "
                "confirm the scope before proceeding."
            ),
            "bullets": connections or ["No connections were extracted for this item."],
            "citations": cites[:5],
        },
        {
            "heading": "3. Evidence from plant memory",
            "body": (
                f"{len(evidence)} sources were retrieved from the on-premise "
                "plant memory graph and drawing index."
            ),
            "table": {
                "columns": ["Source", "Type", "Document", "Page"],
                "rows": [
                    [
                        c.get("entity") or (c.get("text") or "")[:40],
                        c.get("source_type", ""),
                        c.get("document") or "—",
                        c.get("page") or "—",
                    ]
                    for c in evidence[:12]
                ],
            },
            "citations": cites,
        },
        {
            "heading": "4. Impact assessment",
            "bullets": [
                "Process: confirm hydraulic impact on the affected run.",
                "Safety: confirm relief scenarios remain bounded.",
                "Control: confirm loop tuning and interlocks remain valid.",
                "Mechanical: confirm rating, materials and spec break.",
            ],
        },
        {
            "heading": "5. Review and approval",
            "body": (
                "This note was assembled by Meshcore from on-premise sources. "
                "It is a DRAFT: a named engineer must verify every clause and "
                "every citation before this change proceeds."
            ),
        },
    ]


def _calc_request(prompt: str, evidence: list[dict]) -> dict:
    """Build a calculation REQUEST — never a result — from the prompt.

    Values a user stated explicitly are used; anything absent falls back to a
    labelled assumption, because a silent default is how a wrong number ends
    up in a document. Every input carries its source into the provenance.
    """
    def number(patterns: list[str]) -> Optional[float]:
        for pat in patterns:
            m = re.search(pat, prompt or "", re.I)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
        return None

    flow = number([r"(\d+(?:\.\d+)?)\s*m3/h", r"(\d+(?:\.\d+)?)\s*m³/h"])
    dia_in = number([r"(\d+(?:\.\d+)?)\s*(?:-)?\s*inch", r"(\d+(?:\.\d+)?)\s*\""])
    dia_mm = number([r"(\d+(?:\.\d+)?)\s*mm"])
    length = number([r"(\d+(?:\.\d+)?)\s*m\b(?!3)(?!m)"])

    inputs: dict[str, Any] = {}
    inputs["flow"] = {
        "value": flow if flow is not None else 120.0,
        "unit": "m3/h",
        "source": "user_prompt" if flow is not None else "ASSUMED (not stated)",
    }
    if dia_mm is not None:
        inputs["diameter"] = {"value": dia_mm, "unit": "mm", "source": "user_prompt"}
    elif dia_in is not None:
        inputs["diameter"] = {"value": dia_in, "unit": "in", "source": "user_prompt"}
    else:
        inputs["diameter"] = {
            "value": 150.0, "unit": "mm", "source": "ASSUMED (not stated)",
        }
    inputs["length"] = {
        "value": length if length is not None else 50.0,
        "unit": "m",
        "source": "user_prompt" if length is not None else "ASSUMED (not stated)",
    }
    inputs["density"] = {"value": 850.0, "unit": "kg/m3", "source": "ASSUMED hydrocarbon"}
    inputs["viscosity"] = {"value": 3.2, "unit": "cp", "source": "ASSUMED hydrocarbon"}

    low = (prompt or "").lower()
    if "velocity" in low:
        operation, unit = "fluid_velocity", "m/s"
        inputs = {k: v for k, v in inputs.items() if k in ("flow", "diameter")}
    elif "reynolds" in low:
        operation, unit = "reynolds_number", ""
    elif "power" in low:
        operation, unit = "pump_hydraulic_power", ""
        inputs["delta_p"] = {"value": 6.0, "unit": "bar", "source": "ASSUMED duty"}
    else:
        operation, unit = "line_pressure_drop_darcy_weisbach", "bar"
    return {"operation": operation, "inputs": inputs, "output_unit": unit}


def _tracker_args(prompt: str, entities: list[dict]) -> dict:
    return {
        "title": prompt.strip()[:60] or "Meshcore tracker",
        "columns": ["Tag", "Type", "Description", "Document", "Page",
                    "Confidence", "Needs review"],
        "rows": [
            [
                e.get("tag", ""),
                e.get("type", ""),
                e.get("label", ""),
                e.get("document", ""),
                e.get("page"),
                e.get("confidence"),
                "YES" if e.get("needs_review") else "",
            ]
            for e in entities
        ],
        "citations": [
            {
                "label": e.get("tag", ""),
                "document": e.get("document", ""),
                "page": e.get("page"),
                "source_type": "pid",
            }
            for e in entities[:40]
        ],
    }


def _grounded_doc_args(prompt: str, tag: str, evidence: list[dict]) -> dict:
    """A cited report about a plant subject, built from retrieved evidence.

    No model writes this. The alternative was to hand the evidence to the
    local chat model and ask for prose, which at 1B produces confident
    paraphrase that drops half the tags — and a document whose sentences no
    longer match its own citation table is worse than a plainly structured
    one. So the structure is deterministic and every claim in it is a row
    that came out of the graph or the drawing index.
    """
    cites = [
        {
            "label": c.get("entity") or (c.get("text") or "")[:50],
            "document": c.get("document") or "",
            "page": c.get("page"),
            "bbox": c.get("bbox"),
            "source_type": c.get("source_type", "pid"),
        }
        for c in evidence[:12]
    ]
    edges = [
        f"{c.get('entity')} → {c.get('relation')} → {c.get('target')}"
        for c in evidence
        if c.get("source_type") == "graph" and c.get("entity") and c.get("target")
    ][:14]
    subject = tag or "the requested subject"

    sections = [
        {
            "heading": "1. Request",
            "body": prompt.strip(),
            "citations": cites[:3],
        },
        {
            "heading": "2. What plant memory holds",
            "body": (
                f"{len(evidence)} sources were retrieved for {subject} from "
                "this project's on-premise plant memory graph and drawing "
                "index. Nothing below came from outside them."
                if evidence else
                f"No evidence was retrieved for {subject} in this project. "
                "Nothing in this document should be relied on; ingest the "
                "relevant drawing and regenerate it."
            ),
            "citations": cites[:6],
        },
    ]
    if edges:
        sections.append(
            {
                "heading": "3. Extracted connections",
                "bullets": edges,
                "citations": cites[:8],
            }
        )
    if evidence:
        sections.append(
            {
                "heading": f"{len(sections) + 1}. Evidence table",
                "table": {
                    "columns": ["Source", "Type", "Document", "Page",
                                "Confidence"],
                    "rows": [
                        [
                            c.get("entity") or (c.get("text") or "")[:40],
                            c.get("source_type", ""),
                            c.get("document") or "—",
                            c.get("page") or "—",
                            (
                                f"{float(c['confidence']):.0%}"
                                if c.get("confidence") is not None else "—"
                            ),
                        ]
                        for c in evidence[:24]
                    ],
                },
                "citations": cites,
            }
        )
    sections.append(
        {
            "heading": f"{len(sections) + 1}. Review",
            "body": (
                "Meshcore assembled this from on-premise sources. It is a "
                "DRAFT: a named engineer must verify every claim and every "
                "citation before it is used."
            ),
        }
    )
    return {
        "title": prompt.strip()[:60] or f"Report — {subject}",
        "subtitle": prompt.strip()[:120],
        "sections": sections,
    }


_TRACKER_COLUMNS = ["Tag", "Type", "Description", "Document", "Page",
                    "Confidence", "Needs review"]


def _tracker_doc_args(prompt: str, entities: list[dict]) -> dict:
    """The same tracker, as prose sections, for a DOCX or PDF render.

    Asking for "a PDF of every instrument" should not silently hand back a
    spreadsheet, so the tabular data is wrapped in a document instead of the
    request being redirected to the format that was easier to produce.
    """
    rows = _tracker_args(prompt, entities)["rows"]
    review = sum(1 for e in entities if e.get("needs_review"))
    return {
        "title": prompt.strip()[:60] or "Meshcore tracker",
        "subtitle": f"{len(entities)} items extracted from this project",
        "sections": [
            {
                "heading": "1. Scope",
                "body": (
                    f"{prompt.strip()}\n\n"
                    f"{len(entities)} items were read from this project's "
                    "extracted plant memory. Every row is traceable to the "
                    "drawing and page it was extracted from."
                ),
            },
            {
                "heading": "2. Items",
                "table": {"columns": _TRACKER_COLUMNS, "rows": rows},
                "citations": [
                    {
                        "label": e.get("tag", ""),
                        "document": e.get("document", ""),
                        "page": e.get("page"),
                        "source_type": "pid",
                    }
                    for e in entities[:40]
                ],
            },
            {
                "heading": "3. Review status",
                "body": (
                    f"{review} of {len(entities)} items were flagged by a "
                    "validation rule and are marked YES in the Needs review "
                    "column. They are extractions, not settled fact, and a "
                    "named engineer must confirm them."
                    if review else
                    "No item was flagged by a validation rule. Confidence "
                    "scores are per-extraction and are listed per row."
                ),
            },
        ],
    }


_UNVERIFIED_NOTE = (
    "Generated from the local language model's own knowledge. This project "
    "holds no evidence for it, so nothing here is cited to a drawing or a "
    "document and none of it has been verified. Treat it as a starting "
    "draft, not as plant data."
)


def _general_table_args(prompt: str, drafted: dict) -> dict:
    """Shape a drafted table for `render_xlsx`.

    The provenance row is not decoration. Everything else this agent renders
    is traceable to a drawing or a document; this is not, and a spreadsheet
    that does not say so is indistinguishable from one that is.
    """
    columns = [str(c) for c in (drafted.get("columns") or ["Item", "Notes"])][:6]
    width = len(columns)

    # The model is told 6 columns and often sends 10, or sends rows as objects
    # rather than arrays. Both are normalised here rather than dropped: a row
    # silently discarded for being the wrong shape produces a spreadsheet with
    # headers and no data, which is worse than a ragged one.
    rows: list[list] = []
    for row in drafted.get("rows") or []:
        if isinstance(row, dict):
            values = [row.get(c, "") for c in columns]
        elif isinstance(row, (list, tuple)):
            values = list(row)
        else:
            values = [row]
        values = [("" if v is None else v) for v in values[:width]]
        values += [""] * (width - len(values))   # pad short rows
        if any(str(v).strip() for v in values):
            rows.append(values)
        if len(rows) >= 25:
            break
    return {
        "title": str(drafted.get("title") or prompt.strip()[:60] or "Generated table"),
        "columns": columns,
        "rows": rows,
        "citations": [
            {
                "label": f"UNVERIFIED — model-generated. {_UNVERIFIED_NOTE}",
                "document": "",
                "source_type": "model",
            }
        ],
    }


def _general_doc_args(prompt: str, drafted: dict) -> dict:
    """Shape a drafted report for `render_docx`, with the caveat up front."""
    sections = [
        {
            "heading": str(s.get("heading") or f"Section {i}"),
            "body": str(s.get("body") or ""),
            "bullets": [str(b) for b in (s.get("bullets") or [])][:10],
        }
        for i, s in enumerate(drafted.get("sections") or [], start=1)
        if isinstance(s, dict)
    ][:6]
    # Prepended, not appended: the reader must meet the caveat before the
    # content, not after they have already believed it.
    sections.insert(
        0,
        {
            "heading": "Provenance — UNVERIFIED",
            "body": _UNVERIFIED_NOTE,
            "citations": [
                {
                    "label": "Model knowledge — no plant evidence",
                    "document": "",
                    "source_type": "model",
                }
            ],
        },
    )
    return {
        "title": str(drafted.get("title") or prompt.strip()[:60] or "Generated report"),
        "subtitle": prompt.strip()[:120],
        "sections": sections,
    }


def _calc_note_sections(prompt: str, calc: dict) -> list[dict]:
    # Each input is a citation: an engineering number is only reviewable if the
    # reader can see where every value in it came from.
    input_cites = [
        {
            "label": f"{p['input']} = {p['value']} {p['unit']}".strip(),
            "document": p.get("source", ""),
            "source_type": "calculation-input",
        }
        for p in calc.get("provenance", [])
    ]
    return [
        {"heading": "1. Request", "body": prompt.strip()},
        {
            "heading": "2. Result",
            "body": (
                f"{calc['operation']} = {calc['result']} {calc['unit']}\n"
                f"Calculation ID: {calc['calculation_id']}\n"
                f"Status: {calc['status']}"
            ),
        },
        {
            "heading": "3. Formula and working",
            "body": calc["formula"],
            "bullets": calc.get("intermediate_steps", []),
        },
        {
            "heading": "4. Inputs and provenance",
            "table": {
                "columns": ["Input", "Value", "Unit", "Source"],
                "rows": [
                    [p["input"], p["value"], p["unit"], p["source"]]
                    for p in calc.get("provenance", [])
                ],
            },
            "citations": input_cites,
        },
        {
            "heading": "5. Verification",
            "body": (
                f"{calc['verification']}\nEngine version {calc['engine_version']}. "
                f"Reference: {calc.get('reference', '—')}.\n\n"
                "The number above was produced by Meshcore's deterministic "
                "calculation engine, not by a language model. Inputs marked "
                "ASSUMED were not supplied and must be confirmed."
            ),
            "bullets": calc.get("warnings", []),
        },
    ]


# ── the loop ──────────────────────────────────────────────────
def _with_context(prompt: str, history: list[dict] | None) -> str:
    """Prompt plus the last user turn, for classification only.

    Only the preceding *user* turn is borrowed: assistant text is long and
    would swamp the keyword match that `classify_task` does.

    And only when this sentence needs it. "Now put that in a spreadsheet"
    names no subject and has to look back; "make me a PDF report on P-101"
    names one, and borrowing anyway let the previous turn's words win — asked
    for a PDF about P-101 right after asking for an excel of all instruments,
    it produced an instrument spreadsheet. The thread fills gaps in a
    request; it does not overrule it.
    """
    if not history or _PLANT_SUBJECT_RE.search(prompt or ""):
        return prompt
    if not _refers_back(prompt):
        return prompt
    # Walk back to the last user turn that actually named a subject, not just
    # the previous one. "excel of all instruments" → "now make that a PDF" →
    # "also as a word doc" borrowed the middle turn, which names no subject
    # either, so the chain lost the instruments after one hop and fell back
    # to inventing a document. `_retrieval_query` walks back for the same
    # reason on the chat path.
    for turn in reversed(history):
        if turn.get("role") != "user":
            continue
        content = turn.get("content", "")
        if _PLANT_SUBJECT_RE.search(content):
            return content + "\n" + prompt
    return prompt


# Words that point at something already said, plus the shape of a request too
# short to carry a subject of its own ("as a PDF", "again in excel").
_BACK_REFERENCE_RE = re.compile(
    r"\b(that|this|it|its|those|these|them|same|again|also|too|instead|"
    r"above|previous|earlier)\b",
    re.I,
)


def _refers_back(prompt: str) -> bool:
    """Is this a follow-up, or a new request that simply is not about plant?

    Borrowing the thread whenever the sentence named no plant subject was too
    eager: "make a spreadsheet of the top vision models", asked after an
    instrument tracker, inherited "all instruments" and produced an
    instrument tracker instead of what was asked for. A follow-up either
    points back at something explicitly or is too short to stand alone.
    """
    text = (prompt or "").strip()
    if not text:
        return False
    if _BACK_REFERENCE_RE.search(text):
        return True
    return len(text.split()) <= 5


def _resolve_format(prompt: str, prompt_in_context: str, task: str) -> str:
    """The format this request asks for, preferring the sentence just typed.

    A format named in the current sentence is never overridden by one named
    earlier in the thread, whatever else the thread contributes.
    """
    default = _DEFAULT_FORMAT_BY_TASK.get(task, FORMAT_DOCX)
    for pattern, fmt in _FORMAT_RULES:
        if pattern.search(prompt or ""):
            return fmt
    return detect_format(prompt_in_context, default=default)


async def run_agent(
    session: Session,
    state,
    project_id: int,
    prompt: str,
    out_dir: Path,
    clearance: str = "internal",
    session_id: str = "agent",
    history: list[dict] | None = None,
) -> AsyncIterator[dict]:
    """Execute one bounded agent task, yielding SSE-shaped events."""
    budget = AgentBudget()
    ctx = ToolContext(session, state, project_id, out_dir, clearance)

    # A follow-up like "now put that in a spreadsheet" names its subject only
    # in the previous turn, so the task is classified against the thread, not
    # the sentence alone.
    prompt_in_context = _with_context(prompt, history)
    task = classify_task(prompt_in_context)
    tag = find_tag(prompt_in_context)
    fmt = _resolve_format(prompt, prompt_in_context, task)
    yield {
        "type": "status", "stage": "intake",
        "format": fmt,
        "detail": f"Task classified as {task}" + (f" for {tag}" if tag else ""),
    }
    audit.record_event(
        user_action="agent:intake", session_id=session_id,
        tool_name="agent", result_status=task,
    )

    plan = build_plan(prompt, task, fmt, query=prompt_in_context)
    yield {
        "type": "plan",
        "task": task,
        "format": fmt,
        "steps": [{"tool": p.tool, "why": p.why} for p in plan],
        "budget": budget.as_dict(),
    }

    evidence: list[dict] = []
    entities: list[dict] = []
    drafted: Optional[dict] = None
    calc: Optional[dict] = None
    artifacts: list[dict] = []
    failures: list[str] = []

    for step in plan:
        spent = budget.exhausted()
        if spent:
            yield {"type": "status", "stage": "budget",
                   "detail": f"Stopping: {spent}"}
            break

        decision, reason = policy_decision(step, clearance)
        yield {
            "type": "policy", "tool": step.tool,
            "decision": decision, "reason": reason,
        }
        if decision == "deny":
            failures.append(f"{step.tool} denied: {reason}")
            audit.record_event(
                user_action="agent:policy_deny", session_id=session_id,
                tool_name=step.tool, result_status="denied",
            )
            continue

        # Fill deferred arguments now that earlier steps have produced data.
        args = dict(step.arguments)
        defer = args.pop("_defer", None)
        if defer == "moc":
            args = {
                "title": f"Management of Change — {tag or 'Proposed change'}",
                "subtitle": prompt.strip()[:120],
                "sections": _moc_sections(prompt, tag, evidence),
            }
        elif defer == "general_table":
            if not drafted:
                failures.append("drafting produced nothing; file skipped")
                continue
            args = _general_table_args(prompt, drafted)
        elif defer == "general_doc":
            if not drafted:
                failures.append("drafting produced nothing; file skipped")
                continue
            args = _general_doc_args(prompt, drafted)
        elif defer == "tracker":
            args = _tracker_args(prompt, entities)
        elif defer == "tracker_doc":
            args = _tracker_doc_args(prompt, entities)
        elif defer == "grounded_doc":
            args = _grounded_doc_args(prompt, tag, evidence)
        elif defer == "calc":
            args = _calc_request(prompt, evidence)
        elif defer == "calc_note":
            if not calc:
                failures.append("calculation produced no result; note skipped")
                continue
            args = {
                "title": f"Calculation record — {calc['calculation_id']}",
                "subtitle": calc["operation"],
                "sections": _calc_note_sections(prompt, calc),
            }

        yield {"type": "tool", "tool": step.tool, "status": "running",
               "detail": step.why}
        budget.tool_calls += 1
        result: ToolResult = await tools.invoke(ctx, step.tool, args)

        if not result.ok:
            failures.append(f"{step.tool}: {result.error}")
            yield {"type": "tool", "tool": step.tool, "status": "failed",
                   "detail": result.error}
            budget.replans += 1
            continue

        # OBSERVE: fold the output into the working set.
        if step.tool == "retrieve":
            evidence.extend(result.output.get("context", []))
            detail = f"{result.output.get('hits', 0)} hits"
        elif step.tool == "list_entities":
            entities = result.output.get("entities", [])
            detail = f"{len(entities)} entities"
        elif step.tool == "draft":
            drafted = result.output
            rows = len(drafted.get("rows") or drafted.get("sections") or [])
            detail = f"{rows} rows/sections drafted (UNVERIFIED)"
        elif step.tool == "calculate":
            calc = result.output
            detail = f"{calc['result']} {calc['unit']} ({calc['calculation_id']})"
        elif result.artifact:
            artifacts.append(result.artifact)
            detail = f"{result.artifact['name']} · {result.artifact['citations']} citations"
        else:
            detail = "ok"

        yield {"type": "tool", "tool": step.tool, "status": "done", "detail": detail}
        await asyncio.sleep(0)

    # ── VERIFY ────────────────────────────────────────────────
    checks = {
        "has_evidence": bool(evidence or entities),
        "artifact_rendered": bool(artifacts),
        "citations_present": any(a.get("citations", 0) > 0 for a in artifacts),
        "calculation_reviewed": (
            calc.get("status") == "NEEDS_ENGINEERING_REVIEW" if calc else None
        ),
        "budget_respected": budget.exhausted() is None,
    }
    verified = all(v for v in checks.values() if v is not None) or not artifacts
    yield {"type": "verify", "checks": checks, "passed": verified}

    audit.record_event(
        user_action="agent:deliver", session_id=session_id, tool_name="agent",
        retrieval_count=len(evidence),
        result_status="ok" if artifacts else ("partial" if evidence else "empty"),
    )
    message = _deliver_message(
        task=task,
        fmt=fmt,
        artifacts=artifacts,
        calc=calc,
        evidence_count=len(evidence),
        entity_count=len(entities),
        failures=failures,
        budget=budget,
    )
    yield {
        "type": "agent_done",
        "task": task,
        "format": fmt,
        "message": message,
        "artifacts": artifacts,
        "calculation": calc,
        "evidence_count": len(evidence),
        "entity_count": len(entities),
        "failures": failures,
        "budget": budget.as_dict(),
        "verified": verified,
    }


# ── DELIVER: the sentence the assistant says about what it built ──
# This used to be assembled in the browser, which meant the turn saved to the
# database had an empty body: reopening the thread showed a file with no
# explanation of where it came from, and the transcript read as if the user's
# request had gone unanswered. The prose belongs with the run that produced
# it, so the live stream and the reloaded thread say the same thing.
def _deliver_message(
    *,
    task: str,
    fmt: str,
    artifacts: list[dict],
    calc: Optional[dict],
    evidence_count: int,
    entity_count: int,
    failures: list[str],
    budget: AgentBudget,
) -> str:
    lines: list[str] = []
    if artifacts:
        names = ", ".join(f"`{a['name']}`" for a in artifacts)
        cited = sum(int(a.get("citations") or 0) for a in artifacts)
        # "a XLSX" reads as carelessly as the document would be written.
        article = "an" if fmt[:1].lower() in "aeioux" else "a"
        source_note = (
            f"{entity_count} extracted entities"
            if task == TASK_TRACKER and entity_count
            else f"{evidence_count} retrieved sources"
        )
        if task == TASK_GENERAL_DOC:
            lines.append(
                f"I built {names} as {article} {fmt.upper()}. This project holds no "
                "evidence for the subject, so the content came from the local "
                "model's own knowledge and the file is labelled UNVERIFIED "
                "throughout — treat it as a starting draft."
            )
        else:
            lines.append(
                f"I built {names} as {article} {fmt.upper()} from {source_note}, with "
                f"{cited} citation{'s' if cited != 1 else ''} recorded in its "
                "provenance sidecar."
            )
        lines.append(
            "\n\nIt is downloadable below and in the Deliverables tab. Every "
            "artefact is a DRAFT until a named engineer signs it off."
        )
    elif failures:
        lines.append(
            "I could not produce the file. " + "; ".join(failures[:3]) + "."
        )
    else:
        lines.append(
            f"I retrieved {evidence_count} source"
            f"{'s' if evidence_count != 1 else ''} for this, but the task did "
            "not call for a file — ask for a spreadsheet, a document or a PDF "
            "and I will render one."
        )

    if calc:
        lines.append(
            f"\n\n**Calculation {calc['calculation_id']}:** {calc['result']} "
            f"{calc['unit']} — `{calc['formula']}`\nStatus: {calc['status']}. "
            "The number came from the deterministic engine, not from a "
            "language model."
        )
    if artifacts and failures:
        lines.append(f"\n\n_Also blocked:_ {'; '.join(failures)}")

    b = budget.as_dict()
    lines.append(
        f"\n\n_Budget: {b['tool_calls']}/{b['max_tool_calls']} tool calls, "
        f"{b['replans']}/{b['max_replans']} replans, {b['elapsed_s']}s of "
        f"{b['wall_clock_seconds']}s._"
    )
    return "".join(lines)
