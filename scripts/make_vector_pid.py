"""Generate a BORN-DIGITAL (vector) demo P&ID.

`make_demo_pid.py` produces a raster PNG and wraps it in a PDF — that is the
scanned-drawing case. But most P&IDs a refinery actually holds were exported
from AutoCAD / SmartPlant and carry a real text and geometry layer.

This script emits that second case: a PDF whose tags are selectable text and
whose pipes are drawn line segments. It shares `make_demo_pid.SPEC_ENTITIES`,
so the existing golden `entities.json` is the ground truth for both, and the
measured F1 of the two paths is directly comparable.

    python scripts/make_vector_pid.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from make_demo_pid import (  # noqa: E402
    RELATIONSHIPS,
    SPEC_ENTITIES,
    SPEC_LINES,
)

DEMO_DIR = REPO / "data" / "demo"
PID_DIR = DEMO_DIR / "pid"
EXPECTED_DIR = DEMO_DIR / "expected"

# A4 landscape at 2x, the shape a real P&ID sheet is plotted at.
PAGE_W, PAGE_H = 1190.0, 842.0

INK = (0.12, 0.16, 0.24)
BLUE = (0.14, 0.39, 0.92)
GRAY = (0.39, 0.45, 0.55)

# Filled in by build(): where each run was actually drawn.
RUN_GEOMETRY: dict[str, list[tuple[float, float]]] = {}


def _rect(cx: float, cy: float, w: float, h: float) -> pymupdf.Rect:
    """Spec fractions (centre + size) → an absolute page rectangle."""
    x0 = (cx - w / 2) * PAGE_W
    y0 = (cy - h / 2) * PAGE_H
    return pymupdf.Rect(x0, y0, x0 + w * PAGE_W, y0 + h * PAGE_H)


def line_runs() -> dict[str, tuple[str, str]]:
    """Map each line tag to the (upstream, downstream) equipment it joins.

    Derived from RELATIONSHIPS: `A TO L-x` followed by `L-x TO B` means the
    run named L-x physically spans A to B.
    """
    upstream: dict[str, str] = {}
    downstream: dict[str, str] = {}
    for src, rel, tgt, _c in RELATIONSHIPS:
        if rel != "TO":
            continue
        if tgt.startswith("L-"):
            upstream[tgt] = src
        if src.startswith("L-"):
            downstream[src] = tgt
    return {
        tag: (upstream[tag], downstream[tag])
        for tag in set(upstream) & set(downstream)
    }


def build() -> Path:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    shape = page.new_shape()
    by_tag = {e[5]: e for e in SPEC_ENTITIES}

    # ── process runs, drawn edge-to-edge between the equipment they join ──
    # SPEC_LINES holds nominal centres that stop short of the equipment, so a
    # sheet drawn from them has visible gaps and nothing is actually connected.
    # A real P&ID lands the pipe on the symbol; extraction can only recover a
    # connection that the drawing genuinely makes.
    for tag, (a_tag, b_tag) in line_runs().items():
        a, b = by_tag.get(a_tag), by_tag.get(b_tag)
        if not a or not b:
            continue
        ra, rb = _rect(a[0], a[1], a[2], a[3]), _rect(b[0], b[1], b[2], b[3])
        if ra.x0 > rb.x0:
            ra, rb = rb, ra
        y = (ra.y0 + ra.height / 2 + rb.y0 + rb.height / 2) / 2
        start = pymupdf.Point(ra.x1, y)
        end = pymupdf.Point(rb.x0, y)
        if abs((ra.y0 + ra.height / 2) - (rb.y0 + rb.height / 2)) > 6:
            # Dog-leg: horizontal out, vertical across, horizontal in.
            midx = (start.x + end.x) / 2
            pts = [
                start,
                pymupdf.Point(midx, ra.y0 + ra.height / 2),
                pymupdf.Point(midx, rb.y0 + rb.height / 2),
                end,
            ]
            pts[0] = pymupdf.Point(ra.x1, ra.y0 + ra.height / 2)
            pts[-1] = pymupdf.Point(rb.x0, rb.y0 + rb.height / 2)
        else:
            pts = [start, end]
        for i in range(len(pts) - 1):
            shape.draw_line(pts[i], pts[i + 1])
        shape.finish(color=INK, width=2.0)
        RUN_GEOMETRY[tag] = [(p.x / PAGE_W, p.y / PAGE_H) for p in pts]

    # ── equipment / instrument / valve symbols ──
    for cx, cy, w, h, etype, tag, label, _conf in SPEC_ENTITIES:
        if etype == "process_line":
            continue
        r = _rect(cx, cy, w, h)
        if etype == "instrument":
            shape.draw_circle(pymupdf.Point(r.x0 + r.width / 2, r.y0 + r.height / 2),
                              r.width / 2)
            shape.finish(color=BLUE, width=1.4)
        elif etype == "valve":
            # Bow-tie: the ISA control-valve body.
            shape.draw_polyline([
                pymupdf.Point(r.x0, r.y0), pymupdf.Point(r.x1, r.y1),
                pymupdf.Point(r.x0, r.y1), pymupdf.Point(r.x1, r.y0),
                pymupdf.Point(r.x0, r.y0),
            ])
            shape.finish(color=GRAY, width=1.4)
        else:
            shape.draw_rect(r)
            shape.finish(color=INK, width=1.6)
    # ── instrument signal leads (ISA-5.1 dashed) ──
    # A real P&ID states which equipment an instrument belongs to by drawing a
    # lead from the bubble to its tap point. Omitting them would leave the
    # topology layer nothing to read but distance.
    for src, rel, tgt, _conf in RELATIONSHIPS:
        if rel not in ("HAS_INSTRUMENT", "HAS_VALVE"):
            continue
        host, inst = by_tag.get(src), by_tag.get(tgt)
        if not host or not inst:
            continue
        hr, ir = _rect(host[0], host[1], host[2], host[3]), _rect(inst[0], inst[1], inst[2], inst[3])
        a = pymupdf.Point(ir.x0 + ir.width / 2, ir.y0 + ir.height / 2)
        b = pymupdf.Point(hr.x0 + hr.width / 2, hr.y0 + hr.height / 2)
        shape.draw_line(a, b)
        shape.finish(color=GRAY, width=0.7, dashes="[2 2] 0")

    shape.commit()

    # ── tag text: this is what makes the sheet born-digital ──
    for cx, cy, w, h, etype, tag, label, _conf in SPEC_ENTITIES:
        r = _rect(cx, cy, w, h)
        if etype == "process_line":
            pts = RUN_GEOMETRY.get(tag) or SPEC_LINES.get(tag)
            if pts:
                mx = (pts[0][0] + pts[-1][0]) / 2 * PAGE_W
                my = (pts[0][1] + pts[-1][1]) / 2 * PAGE_H - 5
            else:
                mx, my = r.x0, r.y0
            page.insert_text((mx - 14, my), tag, fontsize=8, color=INK)
        elif etype == "instrument":
            page.insert_text(
                (r.x0 + 2, r.y0 + r.height / 2 + 3), tag, fontsize=7, color=BLUE
            )
        else:
            page.insert_text((r.x0, r.y1 + 10), tag, fontsize=9, color=INK)
            page.insert_text((r.x0, r.y1 + 20), label, fontsize=6, color=GRAY)

    # Title block — deliberate boilerplate the grammar must NOT read as tags.
    page.insert_text((24, PAGE_H - 46), "UNIT A - PROCESS FLOW", fontsize=11, color=INK)
    page.insert_text((24, PAGE_H - 32), "DWG 1023   REV 3   SHEET 1 OF 1",
                     fontsize=8, color=GRAY)
    page.insert_text((24, PAGE_H - 20), "NOTE 1: BORN-DIGITAL VECTOR TEST SHEET",
                     fontsize=7, color=GRAY)

    out = PID_DIR / "unit-a-pid-vector.pdf"
    doc.save(out)
    doc.close()
    return out


def build_expected(pdf_name: str) -> Path:
    """Ground truth for the vector sheet — same spec, so F1 is comparable."""
    entities = []
    for cx, cy, w, h, etype, tag, label, conf in SPEC_ENTITIES:
        run = RUN_GEOMETRY.get(tag) or SPEC_LINES.get(tag)
        if etype == "process_line" and run:
            # Ground truth for a line is where the polyline is actually drawn,
            # not the nominal centre in SPEC_ENTITIES — those disagree, and the
            # drawing is what an extractor can be held to.
            pts = run
            xs = [pt[0] for pt in pts]
            ys = [pt[1] for pt in pts]
            x0, y0 = min(xs), min(ys)
            bw, bh = max(xs) - x0, max(ys) - y0
            if bh < 0.015:
                y0 -= (0.015 - bh) / 2
                bh = 0.015
            if bw < 0.015:
                x0 -= (0.015 - bw) / 2
                bw = 0.015
            bbox = [round(x0, 4), round(y0, 4), round(bw, 4), round(bh, 4)]
        else:
            bbox = [round(cx - w / 2, 4), round(cy - h / 2, 4), round(w, 4), round(h, 4)]
        entities.append({
            "type": etype,
            "tag": tag,
            "label": label,
            "bbox": bbox,
            "confidence": conf,
            "raw_text": tag,
        })
    payload = {
        "document": pdf_name,
        "entities": entities,
        "relationships": [
            {"source": s, "relation": r, "target": t, "confidence": c}
            for s, r, t, c in RELATIONSHIPS
        ],
    }
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPECTED_DIR / "entities-vector.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    pdf = build()
    expected = build_expected(pdf.name)
    print(f"wrote {pdf}")
    print(f"wrote {expected}")

    check = pymupdf.open(pdf)
    page = check[0]
    print(f"vector words:    {len(page.get_text('words'))}")
    print(f"drawing paths:   {len(page.get_drawings())}")
    check.close()
