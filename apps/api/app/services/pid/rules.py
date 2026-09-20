"""Engineering rule validation (README §4.5 step 6).

The README's position — and the thing that makes this defensible in front of a
refinery panel — is that violations are *surfaced*, never silently dropped. An
extraction that quietly discards a pump with no discharge line looks better and
is worse: the reviewer has no idea anything is missing.

So every rule here produces a `Violation` carrying the tag it concerns, why it
fired, and how serious it is. Anything that fires marks the affected entity
NEEDS_REVIEW, which the review UI can filter on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .tag_grammar import parse_tag

# Severity ladder: `error` blocks a clean bill of health, `warning` is a
# reviewer's to-do, `info` is context.
SEVERITY_ORDER = {"error": 3, "warning": 2, "info": 1}


@dataclass
class Violation:
    rule: str
    severity: str
    tag: str
    message: str

    def as_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "tag": self.tag,
            "message": self.message,
        }


@dataclass
class ValidationReport:
    violations: list[Violation] = field(default_factory=list)
    needs_review: set[str] = field(default_factory=set)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    def as_dict(self) -> dict:
        return {
            "violations": [v.as_dict() for v in self.violations],
            "needs_review": sorted(self.needs_review),
            "errors": self.error_count,
            "warnings": self.warning_count,
        }


def _index(entities: Iterable[dict]) -> dict[str, dict]:
    return {e["tag"]: e for e in entities if e.get("tag")}


def _edges_for(tag: str, relationships: list[dict]) -> tuple[list[dict], list[dict]]:
    outgoing = [r for r in relationships if r.get("source") == tag]
    incoming = [r for r in relationships if r.get("target") == tag]
    return outgoing, incoming


# ── individual rules ──────────────────────────────────────────
def rule_pump_suction_discharge(
    entities: list[dict], relationships: list[dict]
) -> list[Violation]:
    """Every pump needs a suction and a discharge."""
    out: list[Violation] = []
    for ent in entities:
        parsed = parse_tag(ent.get("tag", ""))
        if parsed.description != "pump":
            continue
        outgoing, incoming = _edges_for(ent["tag"], relationships)
        has_discharge = any(r.get("relation") in ("TO", "CONNECTED_TO") for r in outgoing)
        has_suction = any(r.get("relation") in ("TO", "CONNECTED_TO") for r in incoming)
        if not has_suction:
            out.append(Violation(
                "pump_suction", "error", ent["tag"],
                f"{ent['tag']} has no suction line traced to it.",
            ))
        if not has_discharge:
            out.append(Violation(
                "pump_discharge", "error", ent["tag"],
                f"{ent['tag']} has no discharge line traced from it.",
            ))
    return out


def rule_control_valve_has_loop(
    entities: list[dict], relationships: list[dict]
) -> list[Violation]:
    """A control valve is driven by a loop; its tag must decode to one."""
    out: list[Violation] = []
    for ent in entities:
        if ent.get("type") != "valve":
            continue
        parsed = parse_tag(ent.get("tag", ""))
        if not parsed.valid or not parsed.loop_number:
            out.append(Violation(
                "valve_loop_tag", "warning", ent.get("tag", "?"),
                f"{ent.get('tag')} does not carry a readable loop number.",
            ))
    return out


def rule_no_dangling_instrument(
    entities: list[dict], relationships: list[dict]
) -> list[Violation]:
    """An instrument must measure something — it cannot float unattached."""
    out: list[Violation] = []
    for ent in entities:
        if ent.get("type") != "instrument":
            continue
        _, incoming = _edges_for(ent["tag"], relationships)
        attached = any(
            r.get("relation") in ("HAS_INSTRUMENT", "CONNECTED_TO") for r in incoming
        )
        if not attached:
            out.append(Violation(
                "dangling_instrument", "warning", ent["tag"],
                f"{ent['tag']} is not attached to any equipment or line.",
            ))
    return out


def rule_line_has_spec(entities: list[dict], relationships: list[dict]) -> list[Violation]:
    """A process line should carry a size-spec-service tag."""
    out: list[Violation] = []
    for ent in entities:
        if ent.get("type") != "process_line":
            continue
        if not ent.get("line_size_mm"):
            out.append(Violation(
                "line_spec", "info", ent.get("tag", "?"),
                f"{ent.get('tag')} has no line size in its tag; size/spec unverified.",
            ))
    return out


def rule_line_endpoints(entities: list[dict], relationships: list[dict]) -> list[Violation]:
    """A line that connects nothing is an extraction gap, not a drawing."""
    out: list[Violation] = []
    for ent in entities:
        if ent.get("type") != "process_line":
            continue
        outgoing, incoming = _edges_for(ent["tag"], relationships)
        flow_out = [r for r in outgoing if r.get("relation") in ("TO", "CONNECTED_TO")]
        flow_in = [r for r in incoming if r.get("relation") in ("TO", "CONNECTED_TO")]
        if not flow_in and not flow_out:
            out.append(Violation(
                "line_dangling", "error", ent["tag"],
                f"{ent['tag']} was detected but traced to nothing at either end.",
            ))
        elif not flow_in or not flow_out:
            out.append(Violation(
                "line_open_end", "warning", ent["tag"],
                f"{ent['tag']} is traced at one end only; the other end is unresolved.",
            ))
    return out


def rule_low_confidence(entities: list[dict], relationships: list[dict]) -> list[Violation]:
    """Anything the pipeline is unsure of is named, not hidden."""
    out: list[Violation] = []
    for ent in entities:
        conf = float(ent.get("confidence", 0) or 0)
        if conf < 0.6:
            out.append(Violation(
                "low_confidence", "warning", ent.get("tag", "?"),
                f"{ent.get('tag')} was extracted at {conf:.0%} confidence.",
            ))
    for rel in relationships:
        conf = float(rel.get("confidence", 0) or 0)
        if conf < 0.6:
            out.append(Violation(
                "low_confidence_link", "warning", rel.get("source", "?"),
                f"{rel.get('source')} → {rel.get('target')} asserted at {conf:.0%}.",
            ))
    return out


def rule_duplicate_tags(entities: list[dict], relationships: list[dict]) -> list[Violation]:
    """The same tag twice on one sheet is a genuine drafting/extraction error."""
    seen: dict[str, int] = {}
    for ent in entities:
        tag = ent.get("tag")
        if tag:
            seen[tag] = seen.get(tag, 0) + 1
    return [
        Violation("duplicate_tag", "error", tag, f"{tag} appears {n} times on this sheet.")
        for tag, n in seen.items()
        if n > 1
    ]


ALL_RULES = (
    rule_pump_suction_discharge,
    rule_control_valve_has_loop,
    rule_no_dangling_instrument,
    rule_line_has_spec,
    rule_line_endpoints,
    rule_low_confidence,
    rule_duplicate_tags,
)


def validate(entities: list[dict], relationships: list[dict]) -> ValidationReport:
    """Run every rule and mark the affected entities NEEDS_REVIEW."""
    report = ValidationReport()
    known = _index(entities)
    for rule in ALL_RULES:
        try:
            for violation in rule(entities, relationships):
                report.violations.append(violation)
                if violation.severity in ("error", "warning") and violation.tag in known:
                    report.needs_review.add(violation.tag)
        except Exception as exc:  # a broken rule must not fail an ingest
            report.violations.append(
                Violation("rule_error", "info", "", f"{rule.__name__} failed: {exc}")
            )
    report.violations.sort(
        key=lambda v: (-SEVERITY_ORDER.get(v.severity, 0), v.tag)
    )
    return report


def apply_review_flags(entities: list[dict], report: ValidationReport) -> list[dict]:
    """Stamp NEEDS_REVIEW onto the entities a rule fired on."""
    reasons: dict[str, list[str]] = {}
    for v in report.violations:
        if v.tag and v.severity in ("error", "warning"):
            reasons.setdefault(v.tag, []).append(v.rule)
    for ent in entities:
        tag = ent.get("tag")
        if tag in reasons:
            ent["needs_review"] = True
            ent["review_reasons"] = sorted(set(reasons[tag]))
        else:
            ent.setdefault("needs_review", False)
    return entities
