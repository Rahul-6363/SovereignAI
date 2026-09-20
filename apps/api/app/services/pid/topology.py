"""Topology inference (README §4.5 steps 4–5).

Connectivity is the part of P&ID understanding that research consistently
finds hardest, and it is the part a small vision model is worst at: asked to
emit relationships, it produces plausible-looking pairs that are not on the
drawing. Geometry is a better witness than a 3B model's recall.

So relationships here are *derived*, not believed:

  * an instrument bubble belongs to the equipment or line it sits nearest,
  * a drawn segment that touches two symbols connects them,
  * flow direction on a horizontal run follows the sheet's left-to-right
    convention when no arrowhead is available,
  * instruments sharing a loop number share a loop.

Every derived edge carries the evidence that produced it in `method`, so the
review UI can show *why* a connection was asserted, and a wrong one is a
correction rather than a mystery.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from .tag_grammar import parse_tag, same_loop

# Search radius, in page fractions, for attaching a bubble to its parent.
ATTACH_RADIUS = 0.14
# How close a segment endpoint must be to a symbol to count as touching it.
TOUCH_RADIUS = 0.035

EQUIPMENT_TYPES = {"equipment"}
ATTACHABLE_TYPES = {"instrument", "valve"}
LINE_TYPES = {"process_line"}


def _centre(bbox: list[float]) -> tuple[float, float]:
    if not bbox or len(bbox) != 4:
        return (0.0, 0.0)
    return (bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2)


def _distance(a: list[float], b: list[float]) -> float:
    ax, ay = _centre(a)
    bx, by = _centre(b)
    return math.hypot(ax - bx, ay - by)


def _point_in_or_near(px: float, py: float, bbox: list[float], pad: float) -> bool:
    if not bbox or len(bbox) != 4:
        return False
    x0, y0, w, h = bbox
    return (x0 - pad) <= px <= (x0 + w + pad) and (y0 - pad) <= py <= (y0 + h + pad)


def _point_to_box(px: float, py: float, bbox: list[float]) -> float:
    """Distance from a point to a box — zero inside it.

    Measuring to the box's *centre* instead makes large symbols unreachable:
    a pipe landing on the shell of a 0.14-tall vessel is 0.07 from its centre
    and would fail any sane touch radius, so the connection is never found.
    """
    if not bbox or len(bbox) != 4:
        return float("inf")
    x0, y0, w, h = bbox
    dx = max(x0 - px, 0.0, px - (x0 + w))
    dy = max(y0 - py, 0.0, py - (y0 + h))
    return math.hypot(dx, dy)


def _relation_for(target_type: str) -> str:
    if target_type == "instrument":
        return "HAS_INSTRUMENT"
    if target_type == "valve":
        return "HAS_VALVE"
    return "CONNECTED_TO"


def attach_instruments(
    entities: list[dict], skip_tags: Optional[set[str]] = None
) -> list[dict]:
    """Attach each instrument/valve to its nearest equipment or line."""
    skip = skip_tags or set()
    hosts = [
        e for e in entities
        if e.get("type") in EQUIPMENT_TYPES | LINE_TYPES and e.get("bbox")
    ]
    if not hosts:
        return []

    edges: list[dict] = []
    for ent in entities:
        if ent.get("type") not in ATTACHABLE_TYPES or not ent.get("bbox"):
            continue
        if ent.get("tag") in skip:
            continue
        best: Optional[dict] = None
        best_d = ATTACH_RADIUS
        for host in hosts:
            if host.get("tag") == ent.get("tag"):
                continue
            d = _distance(ent["bbox"], host["bbox"])
            if d < best_d:
                best, best_d = host, d
        if best is None:
            continue
        # Confidence decays with distance: a bubble drawn right on the pump is
        # a stronger claim than one halfway across the sheet.
        proximity = 1.0 - (best_d / ATTACH_RADIUS)
        edges.append({
            "source": best["tag"],
            "relation": _relation_for(ent["type"]),
            "target": ent["tag"],
            "confidence": round(0.55 + 0.4 * proximity, 3),
            "method": f"proximity({best_d:.3f})",
        })
    return edges


def connect_via_segments(
    entities: list[dict],
    segments: Iterable,
    skip_tags: Optional[set[str]] = None,
) -> list[dict]:
    """Connect symbols joined by a drawn line segment.

    This is the high-quality path: on a born-digital sheet the segment IS the
    pipe, so a connection is observed rather than guessed. `skip_tags` carries
    the inline valves, which the pipe passes through rather than ends at.
    """
    skip = skip_tags or set()
    symbols = [
        e for e in entities
        if e.get("bbox") and e.get("type") != "process_line" and e.get("tag") not in skip
    ]
    lines = [e for e in entities if e.get("type") in LINE_TYPES and e.get("bbox")]
    if not symbols:
        return []

    edges: dict[tuple, dict] = {}
    for seg in segments:
        try:
            pts = seg.endpoints()
        except AttributeError:
            continue
        # A dashed lead carries a signal, not process fluid. Reading it as a
        # pipe emits a bogus CONNECTED_TO beside the correct HAS_INSTRUMENT
        # that connect_signal_leads already derived from the same line.
        if getattr(seg, "dashed", False):
            continue
        touched: list[dict] = []
        for (px, py) in pts:
            hit = None
            hit_d = TOUCH_RADIUS
            for sym in symbols:
                d = _point_to_box(px, py, sym["bbox"])
                if d <= hit_d:
                    hit, hit_d = sym, d
            touched.append(hit)

        a, b = touched[0], touched[1]
        if not a or not b or a["tag"] == b["tag"]:
            continue
        # An instrument never sits in the process path; a segment reaching one
        # is its lead, handled as an attachment rather than a pipe run.
        if a.get("type") == "instrument" or b.get("type") == "instrument":
            continue

        # Name the run if a line tag sits on this segment.
        mid = ((seg.x1 + seg.x2) / 2, (seg.y1 + seg.y2) / 2)
        line_tag = None
        for ln in lines:
            if _point_in_or_near(mid[0], mid[1], ln["bbox"], 0.05):
                line_tag = ln["tag"]
                break

        # Left-to-right / top-to-bottom is the drawing convention for flow
        # when there is no arrowhead to read.
        src, tgt = (a, b)
        if (_centre(b["bbox"])[0] < _centre(a["bbox"])[0] - 0.02):
            src, tgt = (b, a)

        if line_tag:
            for pair in ((src["tag"], line_tag), (line_tag, tgt["tag"])):
                key = (pair[0], "TO", pair[1])
                edges[key] = {
                    "source": pair[0], "relation": "TO", "target": pair[1],
                    "confidence": 0.9, "method": "segment+line-tag",
                }
        else:
            key = (src["tag"], "CONNECTED_TO", tgt["tag"])
            edges[key] = {
                "source": src["tag"], "relation": "CONNECTED_TO", "target": tgt["tag"],
                "confidence": 0.82, "method": "segment",
            }
    return list(edges.values())


def _point_to_segment(px: float, py: float, seg) -> float:
    """Perpendicular distance from a point to a segment."""
    dx, dy = seg.x2 - seg.x1, seg.y2 - seg.y1
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return math.hypot(px - seg.x1, py - seg.y1)
    t = max(0.0, min(1.0, ((px - seg.x1) * dx + (py - seg.y1) * dy) / denom))
    return math.hypot(px - (seg.x1 + t * dx), py - (seg.y1 + t * dy))


def inline_valves(entities: list[dict], segments: Iterable) -> tuple[list[dict], set[str]]:
    """Attach valves that sit ON a pipe run to that run's line.

    A block or control valve is a pass-through device: the pipe continues
    through it. Treating it as a run terminus splits one run into two and
    invents an edge into the valve, so an inline valve is identified first and
    then excluded from run-endpoint matching entirely.

    Returns the edges and the set of tags that are inline (to be skipped).
    """
    valves = [e for e in entities if e.get("type") == "valve" and e.get("bbox")]
    lines = [e for e in entities if e.get("type") in LINE_TYPES and e.get("bbox")]
    if not valves or not lines:
        return [], set()

    edges: list[dict] = []
    inline: set[str] = set()
    for valve in valves:
        vx, vy = _centre(valve["bbox"])
        best_seg, best_d = None, max(valve["bbox"][2], valve["bbox"][3]) * 0.8 + 0.005
        for seg in segments:
            if getattr(seg, "dashed", False):
                continue  # a signal lead is not a pipe run
            d = _point_to_segment(vx, vy, seg)
            if d < best_d:
                best_seg, best_d = seg, d
        if best_seg is None:
            continue
        # Which named run is this segment part of?
        mid = ((best_seg.x1 + best_seg.x2) / 2, (best_seg.y1 + best_seg.y2) / 2)
        host = None
        host_d = 0.12
        for ln in lines:
            d = _point_to_box(mid[0], mid[1], ln["bbox"])
            if d < host_d:
                host, host_d = ln, d
        if host is None:
            continue
        inline.add(valve["tag"])
        edges.append({
            "source": host["tag"],
            "relation": "HAS_VALVE",
            "target": valve["tag"],
            "confidence": 0.93,
            "method": "inline-on-run",
        })
    return edges, inline


def connect_signal_leads(
    entities: list[dict],
    segments: Iterable,
    skip_tags: Optional[set[str]] = None,
) -> list[dict]:
    """Link instrument bubbles to their host via the drawn signal lead.

    ISA-5.1 draws the connection from a bubble to its tap point as a dashed
    (or thin solid) lead. That lead is the drawing's own statement of which
    equipment an instrument belongs to — far better evidence than guessing by
    distance, because bubbles are routinely placed well away from their host.
    """
    skip = skip_tags or set()
    bubbles = {
        e["tag"]: e for e in entities
        if e.get("type") in ATTACHABLE_TYPES and e.get("bbox") and e["tag"] not in skip
    }
    hosts = [
        e for e in entities
        if e.get("type") in EQUIPMENT_TYPES | LINE_TYPES and e.get("bbox")
    ]
    if not bubbles or not hosts:
        return []

    edges: dict[tuple, dict] = {}
    for seg in segments:
        try:
            (x1, y1), (x2, y2) = seg.endpoints()
        except (AttributeError, ValueError):
            continue

        for bubble in bubbles.values():
            d_a = _point_to_box(x1, y1, bubble["bbox"])
            d_b = _point_to_box(x2, y2, bubble["bbox"])
            if min(d_a, d_b) > TOUCH_RADIUS:
                continue
            fx, fy = (x2, y2) if d_a <= d_b else (x1, y1)

            best, best_d = None, ATTACH_RADIUS
            for host in hosts:
                if host["tag"] == bubble["tag"]:
                    continue
                d = _point_to_box(fx, fy, host["bbox"])
                if d < best_d:
                    best, best_d = host, d
            if best is None:
                continue
            key = (best["tag"], _relation_for(bubble["type"]), bubble["tag"])
            edges[key] = {
                "source": best["tag"],
                "relation": _relation_for(bubble["type"]),
                "target": bubble["tag"],
                "confidence": 0.92 if getattr(seg, "dashed", False) else 0.88,
                "method": "signal-lead" + ("(dashed)" if getattr(seg, "dashed", False) else ""),
            }
    return list(edges.values())


def chain_lines(entities: list[dict]) -> list[dict]:
    """Infer flow through line tags by horizontal position when geometry is absent.

    The raster path has no segments, so ordering equipment and line tags along
    the sheet is the only structural signal available. It is weaker evidence,
    and the lower confidence says so.
    """
    nodes = [
        e for e in entities
        if e.get("type") in EQUIPMENT_TYPES | LINE_TYPES and e.get("bbox")
    ]
    if len(nodes) < 2:
        return []
    ordered = sorted(nodes, key=lambda e: _centre(e["bbox"])[0])

    edges: list[dict] = []
    for a, b in zip(ordered, ordered[1:]):
        if a["tag"] == b["tag"]:
            continue
        gap = abs(_centre(b["bbox"])[0] - _centre(a["bbox"])[0])
        vertical_gap = abs(_centre(b["bbox"])[1] - _centre(a["bbox"])[1])
        # Items on different bands of the sheet are not a process run.
        if gap > 0.35 or vertical_gap > 0.25:
            continue
        a_is_line = a["type"] in LINE_TYPES
        b_is_line = b["type"] in LINE_TYPES
        if a_is_line == b_is_line:
            continue  # equipment→equipment with no line between: too weak
        edges.append({
            "source": a["tag"],
            "relation": "TO",
            "target": b["tag"],
            "confidence": 0.6,
            "method": "layout-order",
        })
    return edges


def loop_edges(entities: list[dict]) -> list[dict]:
    """Link instruments that share an ISA-5.1 loop (PT-101 ↔ PIC-101)."""
    instruments = [e for e in entities if e.get("type") == "instrument"]
    edges: list[dict] = []
    seen: set[tuple] = set()
    for i, a in enumerate(instruments):
        for b in instruments[i + 1:]:
            if not same_loop(a["tag"], b["tag"]):
                continue
            key = tuple(sorted((a["tag"], b["tag"])))
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "source": a["tag"],
                "relation": "CONNECTED_TO",
                "target": b["tag"],
                "confidence": 0.85,
                "method": "isa-loop",
            })
    return edges


def infer(
    entities: list[dict],
    segments: Optional[Iterable] = None,
    model_relationships: Optional[list[dict]] = None,
) -> list[dict]:
    """Build the relationship set for one page.

    Precedence, strongest evidence first: observed geometry, then the model's
    own claims (kept only when both endpoints exist), then proximity, loop
    membership and layout order.
    """
    tags = {e["tag"] for e in entities if e.get("tag")}
    merged: dict[tuple, dict] = {}

    def add(edge: dict, priority: int) -> None:
        src, tgt = edge.get("source"), edge.get("target")
        if not src or not tgt or src == tgt:
            return
        if src not in tags or tgt not in tags:
            return
        key = (src, edge.get("relation"), tgt)
        prior = merged.get(key)
        if prior is None or priority > prior["_priority"]:
            merged[key] = dict(edge, _priority=priority)

    inline: set[str] = set()
    if segments:
        segments = list(segments)
        # Inline valves are resolved first: everything downstream needs to know
        # which symbols the pipe passes through rather than terminates at.
        valve_edges, inline = inline_valves(entities, segments)
        for e in valve_edges:
            add(e, 45)
        for e in connect_via_segments(entities, segments, skip_tags=inline):
            add(e, 40)
        for e in connect_signal_leads(entities, segments, skip_tags=inline):
            add(e, 38)

    for e in (model_relationships or []):
        # The model's relationships are a claim, not an observation: they are
        # accepted only when both endpoints were independently detected.
        add(dict(e, method=e.get("method", "vision-model")), 30)

    for e in attach_instruments(entities, skip_tags=inline):
        add(e, 20)
    for e in loop_edges(entities):
        add(e, 15)
    if not segments:
        for e in chain_lines(entities):
            add(e, 10)

    out = []
    for edge in merged.values():
        edge.pop("_priority", None)
        out.append(edge)
    return out
