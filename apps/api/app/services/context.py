"""Context assembly for small local models.

Meshcore runs on whatever hardware a plant has, which in the default preset
means `gemma3:1b` on a CPU. A 1B model has two failure modes that a frontier
model hides, and both of them look like the product being wrong:

1. **Silent truncation.** Ollama applies its own default `num_ctx` when the
   caller does not set one. Hand it a prompt longer than that and the front
   of the prompt -- which is where the system rules and the evidence live --
   is dropped without a word. The model then answers from the tail: the
   user's question alone, with no evidence, confidently. Setting `num_ctx`
   explicitly and *fitting the prompt to it here* is the only way to know
   what the model actually read.

2. **Attention dilution.** Even inside the window, a small model degrades
   sharply with irrelevant context. 24 evidence rows of JSON carrying bboxes
   and row ids is worse than 6 rows of plain text, not better.

So this module owns three jobs, all deterministic and all free of extra
model calls (a second round trip on CPU costs seconds the user watches):

  * `fit_history`     -- rolling window of recent turns + a digest of the rest
  * `render_evidence` -- line-oriented evidence, deduped, ranked, budgeted
  * `assemble`        -- puts them together inside a stated token budget and
                         reports exactly what was kept and what was dropped

Nothing here talks to a model. `ContextReport` is returned alongside the
messages so the stream can state the budget it used -- the same honesty the
rest of the system applies to evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

# -- token estimation -----------------------------------------------------
# No tokenizer ships with the air-gapped install and pulling one for an
# estimate is not worth 200 MB. 3.6 chars/token is close for English prose
# with plant tags in it (tags tokenise badly, which pushes the ratio down
# from the usual 4.0). Deliberately pessimistic: over-estimating costs a few
# dropped evidence rows, under-estimating costs a silently truncated prompt.
_CHARS_PER_TOKEN = 3.6


def estimate_tokens(text: str) -> int:
    """Approximate token count for a string. Never returns less than 1."""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN) + 1)


def estimate_messages(messages: Iterable[dict]) -> int:
    """Token cost of a chat message list, including per-message overhead."""
    total = 0
    for m in messages:
        # ~4 tokens of role/delimiter framing per message in every chat
        # template worth supporting.
        total += estimate_tokens(str(m.get("content", ""))) + 4
    return total


# -- model context windows ------------------------------------------------
# What the model can usefully hold, not what it advertises. A 1B model has a
# large trained window and is unreliable well before the end of it, and on
# CPU every token is time the user waits -- so these are the windows Meshcore
# *chooses* to use, set by parameter count.
_WINDOW_BY_PARAMS = (
    (2.0, 4096),     # <=2B  -- gemma3:1b, qwen3:0.6b
    (5.0, 8192),     # <=5B  -- qwen3:4b, qwen2.5vl:3b
)
_DEFAULT_WINDOW = 8192

_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*b\b", re.I)


def model_window(model: str) -> int:
    """Context window Meshcore will ask this model to use, in tokens.

    Derived from the parameter count in the model name because that is the
    one piece of capability information a model tag reliably carries.
    """
    m = _PARAM_RE.search(model or "")
    params = float(m.group(1)) if m else 4.0
    for limit, window in _WINDOW_BY_PARAMS:
        if params <= limit:
            return window
    return _DEFAULT_WINDOW


@dataclass
class ContextBudget:
    """How one prompt's token window is divided.

    The reserve for the answer is subtracted first and is not negotiable: a
    correct answer cut off mid-sentence is still a failed answer.
    """

    window: int
    reserve_for_answer: int
    system: int
    history: int
    evidence: int

    @property
    def prompt(self) -> int:
        return self.window - self.reserve_for_answer


def budget_for(
    model: str, num_predict: int, window: Optional[int] = None
) -> ContextBudget:
    """Split a model's window into system / history / evidence shares.

    Evidence gets the larger share of what is left after the system prompt:
    this is a grounded assistant, and the evidence is the part of the prompt
    that makes an answer true. History only has to carry the referents a
    follow-up needs ("and its upstream?").
    """
    win = window or model_window(model)
    reserve = min(max(int(num_predict) + 64, 192), max(win // 2, 256))
    available = max(win - reserve, 256)
    system = min(int(available * 0.18), 400)
    rest = available - system
    history = int(rest * 0.30)
    evidence = rest - history
    return ContextBudget(
        window=win,
        reserve_for_answer=reserve,
        system=system,
        history=history,
        evidence=evidence,
    )


# -- report ---------------------------------------------------------------
@dataclass
class ContextReport:
    """What was actually put in front of the model.

    Surfaced to the UI so "the model did not see that" is an observation
    rather than a guess.
    """

    model: str
    window: int
    prompt_tokens: int = 0
    reserve_for_answer: int = 0
    history_turns_kept: int = 0
    history_turns_digested: int = 0
    evidence_kept: int = 0
    evidence_total: int = 0
    dropped: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "model": self.model,
            "window": self.window,
            "prompt_tokens": self.prompt_tokens,
            "reserve_for_answer": self.reserve_for_answer,
            "history_turns_kept": self.history_turns_kept,
            "history_turns_digested": self.history_turns_digested,
            "evidence_kept": self.evidence_kept,
            "evidence_total": self.evidence_total,
            "dropped": self.dropped,
        }


# -- history compaction ---------------------------------------------------
_TAG_RE = re.compile(r"\b([A-Z]{1,6}[- _]?\d{2,4}[A-Z0-9]?)\b")

# The turn the user is following up on is worth more than the three before
# it, so the newest turns are kept whole and everything older is digested.
_VERBATIM_TURNS = 4


def _turn_tags(text: str) -> list[str]:
    found = _TAG_RE.findall((text or "").upper())
    return sorted({re.sub(r"[ _]", "-", t) for t in found})


def digest_turns(turns: list[dict]) -> str:
    """Collapse old turns into a few lines, with no model call.

    An LLM-written summary would read better and would cost a second
    inference pass per question on a CPU -- which is the wrong trade at this
    size. What a follow-up actually needs from an old turn is *what was
    asked* and *which tags were involved*; both are extractable.
    """
    if not turns:
        return ""
    asked: list[str] = []
    tags: set[str] = set()
    for t in turns:
        content = str(t.get("content", "")).strip()
        if not content:
            continue
        tags.update(_turn_tags(content))
        if t.get("role") == "user":
            asked.append(content.splitlines()[0][:100])
    lines = ["Earlier in this conversation:"]
    for q in asked[-6:]:
        lines.append(f"- the user asked: {q}")
    if tags:
        lines.append("- tags discussed: " + ", ".join(sorted(tags)[:12]))
    return "\n".join(lines)


def fit_history(
    history: list[dict] | None,
    budget_tokens: int,
    report: Optional[ContextReport] = None,
) -> list[dict]:
    """Recent turns verbatim, older turns as one digest, inside a budget.

    Returns chat messages ready to splice into the request. Truncation is
    per-turn as well as per-window: one 4,000-token assistant answer in the
    history must not be able to evict the question being asked.
    """
    turns = [
        t
        for t in (history or [])
        if t.get("role") in ("user", "assistant")
        and str(t.get("content", "")).strip()
    ]
    if not turns or budget_tokens <= 0:
        if report:
            report.history_turns_kept = 0
            report.history_turns_digested = len(turns)
            if turns:
                report.dropped.append(
                    f"{len(turns)} earlier turns (no history budget)"
                )
        return []

    recent = turns[-_VERBATIM_TURNS:]

    # A single turn may not take more than a third of the history budget.
    per_turn_cap = max(int(budget_tokens / 3), 120)
    kept: list[dict] = []
    spent = 0
    for turn in reversed(recent):          # newest first: it matters most
        content = str(turn["content"])
        cap_chars = int(per_turn_cap * _CHARS_PER_TOKEN)
        if len(content) > cap_chars:
            content = content[:cap_chars].rstrip() + " [...]"
        cost = estimate_tokens(content) + 4
        if spent + cost > budget_tokens and kept:
            break
        kept.append({"role": turn["role"], "content": content})
        spent += cost
    kept.reverse()

    digested = len(turns) - len(kept)
    messages: list[dict] = []
    if digested > 0:
        digest = digest_turns(turns[: len(turns) - len(kept)])
        if digest and spent + estimate_tokens(digest) <= budget_tokens:
            messages.append({"role": "system", "content": digest})
    messages.extend(kept)

    if report:
        report.history_turns_kept = len(kept)
        report.history_turns_digested = digested
        if digested:
            report.dropped.append(
                f"{digested} earlier turns compacted to a digest"
            )
    return messages


# -- evidence compaction --------------------------------------------------
_MAX_TEXT_CHARS = 180


def _row_line(row: dict) -> str:
    """One evidence row as a single readable line.

    JSON was the obvious encoding and the wrong one: braces, quotes and
    repeated key names are a third of the tokens, and a 1B model reads
    `P-101 --HAS_INSTRUMENT--> PI-101` more reliably than the object form.
    """
    kind = str(row.get("source_type") or "chunk")
    doc = str(row.get("document") or "").strip()
    page = row.get("page")
    if doc and page:
        where = f"  ({doc} p{page})"
    elif doc:
        where = f"  ({doc})"
    elif page:
        where = f"  (p{page})"
    else:
        where = ""

    if kind == "graph":
        entity = row.get("entity") or "?"
        target = row.get("target") or "?"
        relation = row.get("relation") or "CONNECTED_TO"
        return f"GRAPH  {entity} --{relation}--> {target}{where}"

    label = str(row.get("entity") or "").strip()
    text = str(row.get("text") or "").strip().replace("\n", " ")
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS].rstrip() + "..."
    tag = "PID   " if kind == "pid" else "TEXT  "
    if label and text and text.lower() != label.lower():
        return f"{tag} {label}: {text}{where}"
    return f"{tag} {label or text}{where}"


def _dedupe_key(row: dict) -> str:
    if str(row.get("source_type")) == "graph":
        return f"g|{row.get('entity')}|{row.get('relation')}|{row.get('target')}"
    return (
        f"{row.get('source_type')}|{row.get('entity')}|"
        f"{str(row.get('text') or '')[:80]}|{row.get('page')}"
    )


def rank_evidence(rows: list[dict], query: str) -> list[dict]:
    """Order rows by usefulness to *this* question, then by confidence.

    Retrieval already ranked by fusion score across the whole corpus. This
    is a second, cheaper pass with the one signal fusion cannot see: whether
    the row mentions a tag the question named. When the context has to be
    cut, rows about the thing being asked about are the ones to keep.
    """
    wanted = set(_turn_tags(query))

    def score(row: dict) -> tuple:
        text = " ".join(
            str(row.get(k) or "")
            for k in ("entity", "target", "text", "relation")
        ).upper()
        hits = sum(1 for tag in wanted if tag in text)
        # Graph edges state a relationship outright; a text chunk implies one.
        kind_bonus = 1 if str(row.get("source_type")) == "graph" else 0
        conf = float(row.get("confidence") or 0.0)
        return (hits, kind_bonus, conf)

    return sorted(rows, key=score, reverse=True)


def render_evidence(
    answer_context: list[dict] | None,
    query: str,
    budget_tokens: int,
    report: Optional[ContextReport] = None,
) -> str:
    """Evidence as budgeted plain text, most useful rows first.

    Deduped before ranking: hybrid retrieval fuses four retrievers and the
    same graph edge routinely arrives from two of them, which used to spend
    a third of the evidence budget saying one thing twice.
    """
    rows = list(answer_context or [])
    total = len(rows)

    seen: set[str] = set()
    unique: list[dict] = []
    for row in rows:
        key = _dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    ordered = rank_evidence(unique, query)

    lines: list[str] = []
    spent = 0
    for row in ordered:
        line = _row_line(row)
        cost = estimate_tokens(line)
        if spent + cost > budget_tokens:
            break
        lines.append(line)
        spent += cost

    if report:
        report.evidence_total = total
        report.evidence_kept = len(lines)
        duplicates = total - len(unique)
        if duplicates > 0:
            report.dropped.append(
                f"{duplicates} duplicate evidence rows merged"
            )
        cut = len(unique) - len(lines)
        if cut > 0:
            report.dropped.append(
                f"{cut} evidence rows beyond the context budget"
            )

    if not lines:
        return "(no evidence was retrieved for this question)"
    return "\n".join(lines)


# -- assembly -------------------------------------------------------------
def assemble(
    *,
    model: str,
    num_predict: int,
    system: str,
    question: str,
    answer_context: list[dict] | None = None,
    history: list[dict] | None = None,
    evidence_header: str = "Evidence retrieved from this plant's memory:",
    window: Optional[int] = None,
) -> tuple[list[dict], dict, ContextReport]:
    """Build the message list and the Ollama options for one turn.

    Returns `(messages, options, report)`. `options` always carries an
    explicit `num_ctx`, because the whole point of budgeting a prompt is void
    if the server then applies a different window to it.
    """
    budget = budget_for(model, num_predict, window)
    report = ContextReport(
        model=model,
        window=budget.window,
        reserve_for_answer=budget.reserve_for_answer,
    )

    system_text = system.strip()
    system_cap = int(budget.system * _CHARS_PER_TOKEN)
    if len(system_text) > system_cap:
        system_text = system_text[:system_cap].rstrip()
        report.dropped.append("system prompt truncated to fit the window")

    evidence_text = render_evidence(
        answer_context, question, budget.evidence, report
    )

    messages: list[dict] = [{"role": "system", "content": system_text}]
    messages.extend(fit_history(history, budget.history, report))
    messages.append(
        {
            "role": "user",
            "content": (
                f"{evidence_header}\n{evidence_text}\n\nQuestion: {question}"
            ),
        }
    )

    # Last line of defence. Everything above respects its own share, but the
    # shares are estimates -- if the total still overruns, history goes first
    # because the evidence is what makes the answer true.
    while estimate_messages(messages) > budget.prompt and len(messages) > 2:
        del messages[1]
        report.history_turns_kept = max(0, report.history_turns_kept - 1)
        if "history evicted to fit the window" not in report.dropped:
            report.dropped.append("history evicted to fit the window")

    report.prompt_tokens = estimate_messages(messages)
    options = {
        "temperature": 0.2,
        "num_predict": int(num_predict),
        "num_ctx": budget.window,
    }
    return messages, options, report
