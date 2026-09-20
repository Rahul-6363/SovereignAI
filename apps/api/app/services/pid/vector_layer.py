"""Vector layer extraction for born-digital P&IDs (README §4.5 steps 1, 2, 4).

Most P&IDs a refinery actually holds were exported from AutoCAD / SmartPlant
and are *vector* PDFs: the tag text and the pipe geometry are stored as data,
not pixels. Asking a 3B vision model to read them back out of a rendered image
throws that away and then pays for the loss in accuracy.

This module reads the data directly:

    words()     exact text + exact bounding boxes — no model, no OCR error
    segments()  drawn line segments, for the line/topology layer

It returns nothing for scanned sheets, which is the correct answer — the
caller then falls back to the tiled vision path. Detecting which kind of
drawing arrived is `has_vector_text`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .tag_grammar import ParsedTag, looks_like_tag, parse_tag

# Title-block / boilerplate text that is tag-shaped but is not a plant tag.
_STOPWORDS = {
    "NOTE", "NOTES", "REV", "REVISION", "SHEET", "SHT", "DWG", "DRAWING",
    "SCALE", "DATE", "BY", "CHK", "APP", "APPD", "REF", "DOC", "PAGE",
    "TITLE", "PROJECT", "CLIENT", "SIZE", "TYP", "DETAIL", "SEC", "SECTION",
    "ISO", "ASME", "API", "ANSI", "DIN", "CONT", "CONTD", "OF",
}

# How close (in page fractions) two text runs must be to merge into one tag.
_MERGE_GAP = 0.012
_MERGE_ROW = 0.008

# Nominal drawn thickness given to a pipe run so overlap tests work on it.
_RUN_THICKNESS = 0.015


@dataclass
class TextItem:
    """One piece of text with its bbox in 0..1 page fractions."""

    text: str
    bbox: list[float]  # [x, y, w, h]
    confidence: float = 0.99  # vector text is exact; only layout is inferred

    @property
    def cx(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2

    @property
    def cy(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2


@dataclass
class SymbolRegion:
    """A drawn shape that a tag can belong to.

    `kind` is read from the path primitives, which is how a P&ID encodes
    meaning: a circle is an instrument bubble, a rectangle is equipment, a
    closed bow-tie is a valve body, a bare polyline is a pipe run.
    """

    bbox: list[float]  # [x, y, w, h] page fractions
    kind: str          # bubble | box | valve | run

    @property
    def cx(self) -> float:
        return self.bbox[0] + self.bbox[2] / 2

    @property
    def cy(self) -> float:
        return self.bbox[1] + self.bbox[3] / 2

    def contains(self, px: float, py: float, pad: float = 0.0) -> bool:
        x0, y0, w, h = self.bbox
        return (x0 - pad) <= px <= (x0 + w + pad) and (y0 - pad) <= py <= (y0 + h + pad)


@dataclass
class Segment:
    """A drawn line segment in 0..1 page fractions."""

    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.0
    dashed: bool = False

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def orientation(self) -> str:
        dx, dy = abs(self.x2 - self.x1), abs(self.y2 - self.y1)
        if dx > dy * 3:
            return "horizontal"
        if dy > dx * 3:
            return "vertical"
        return "diagonal"

    def endpoints(self) -> list[tuple[float, float]]:
        return [(self.x1, self.y1), (self.x2, self.y2)]


def has_vector_text(pdf_page) -> bool:
    """True when this PDF page carries a real text layer worth reading."""
    try:
        return len(pdf_page.get_text("words")) >= 5
    except Exception:
        return False


def words(pdf_page) -> list[TextItem]:
    """Exact text runs with page-fraction bboxes, merged into tag candidates."""
    try:
        raw = pdf_page.get_text("words")
    except Exception:
        return []
    rect = pdf_page.rect
    pw, ph = float(rect.width), float(rect.height)
    if pw <= 0 or ph <= 0:
        return []

    items: list[TextItem] = []
    for w in raw:
        # PyMuPDF word tuple: (x0, y0, x1, y1, text, block, line, word_no)
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], str(w[4])
        if not text.strip():
            continue
        items.append(
            TextItem(
                text=text.strip(),
                bbox=[
                    round(x0 / pw, 5),
                    round(y0 / ph, 5),
                    round((x1 - x0) / pw, 5),
                    round((y1 - y0) / ph, 5),
                ],
            )
        )
    return _merge_runs(items)


def _merge_runs(items: list[TextItem]) -> list[TextItem]:
    """Join text runs split by the PDF writer.

    Tags routinely arrive as separate words — `PI` `-` `101`, or `6"` `-` `P`
    `-` `1501`. Reading them individually loses every tag on the sheet, so
    adjacent runs on the same baseline are concatenated before parsing.
    """
    if not items:
        return []
    ordered = sorted(items, key=lambda t: (round(t.cy, 3), t.bbox[0]))
    merged: list[TextItem] = []
    current = ordered[0]

    for nxt in ordered[1:]:
        same_row = abs(nxt.cy - current.cy) <= _MERGE_ROW
        gap = nxt.bbox[0] - (current.bbox[0] + current.bbox[2])
        if same_row and -_MERGE_ROW <= gap <= _MERGE_GAP:
            x0 = min(current.bbox[0], nxt.bbox[0])
            y0 = min(current.bbox[1], nxt.bbox[1])
            x1 = max(current.bbox[0] + current.bbox[2], nxt.bbox[0] + nxt.bbox[2])
            y1 = max(current.bbox[1] + current.bbox[3], nxt.bbox[1] + nxt.bbox[3])
            joiner = "" if nxt.text.startswith("-") or current.text.endswith("-") else " "
            current = TextItem(
                text=f"{current.text}{joiner}{nxt.text}",
                bbox=[round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5)],
            )
        else:
            merged.append(current)
            current = nxt
    merged.append(current)

    # Keep both the merged run and its parts: "PI-101" wins, but a run that
    # merged two unrelated tags must not swallow either of them.
    return merged + [i for i in ordered if i not in merged]


def segments(pdf_page, min_length: float = 0.01) -> list[Segment]:
    """Drawn line segments in page fractions, for the topology layer."""
    try:
        drawings = pdf_page.get_drawings()
    except Exception:
        return []
    rect = pdf_page.rect
    pw, ph = float(rect.width), float(rect.height)
    if pw <= 0 or ph <= 0:
        return []

    out: list[Segment] = []
    for path in drawings:
        dashes = str(path.get("dashes") or "").strip()
        dashed = bool(dashes) and dashes not in ("[] 0", "[]0", "none")
        width = float(path.get("width") or 0.0)
        for item in path.get("items", []):
            kind = item[0]
            if kind == "l":  # line
                p1, p2 = item[1], item[2]
                seg = Segment(
                    x1=p1.x / pw, y1=p1.y / ph,
                    x2=p2.x / pw, y2=p2.y / ph,
                    width=width / max(pw, ph), dashed=dashed,
                )
                if seg.length >= min_length:
                    out.append(seg)
            elif kind == "re":  # rectangle → four segments
                r = item[1]
                corners = [
                    (r.x0 / pw, r.y0 / ph), (r.x1 / pw, r.y0 / ph),
                    (r.x1 / pw, r.y1 / ph), (r.x0 / pw, r.y1 / ph),
                ]
                for i in range(4):
                    a, b = corners[i], corners[(i + 1) % 4]
                    seg = Segment(a[0], a[1], b[0], b[1], width / max(pw, ph), dashed)
                    if seg.length >= min_length:
                        out.append(seg)
    return out


# Entity type → the symbol shape it is normally drawn as.
_TYPE_TO_KIND = {
    "instrument": "bubble",
    "valve": "valve",
    "equipment": "box",
    "process_line": "run",
}


def _is_closed(items: list) -> bool:
    """True when a polyline returns to its starting point (a symbol body)."""
    lines = [it for it in items if it[0] == "l"]
    if len(lines) < 3:
        return False
    try:
        start, end = lines[0][1], lines[-1][2]
        return abs(start.x - end.x) < 1e-6 and abs(start.y - end.y) < 1e-6
    except Exception:
        return False


def _path_kind(items: list, rect_w: float, rect_h: float) -> str:
    kinds = {it[0] for it in items}
    if kinds == {"c"}:
        return "bubble"
    if kinds == {"re"}:
        return "box"
    if "qu" in kinds:
        return "valve"
    if kinds <= {"l"}:
        # An open polyline is a pipe run however it is angled; only a closed
        # one is a symbol body. Judging by bbox thickness alone mislabels
        # every diagonal run as a valve.
        return "valve" if _is_closed(items) else "run"
    return "box"


def shapes(pdf_page, max_edge: float = 0.4) -> list[SymbolRegion]:
    """Drawn symbol regions in page fractions.

    Each P&ID symbol is emitted as one path, so a path's bounding box is the
    symbol's extent — which is what a tag must be snapped to. Without this the
    pipeline measures distances between *labels*, and a bubble drawn on a pump
    looks no closer to it than to anything else on the sheet.
    """
    try:
        drawings = pdf_page.get_drawings()
    except Exception:
        return []
    rect = pdf_page.rect
    pw, ph = float(rect.width), float(rect.height)
    if pw <= 0 or ph <= 0:
        return []

    out: list[SymbolRegion] = []
    for path in drawings:
        r = path.get("rect")
        if r is None:
            continue
        w, h = float(r.width) / pw, float(r.height) / ph
        if w > max_edge and h > max_edge:
            continue  # border / title block, not a symbol
        kind = _path_kind(path.get("items", []), w, h)
        x0, y0 = float(r.x0) / pw, float(r.y0) / ph
        # A horizontal run has zero height, which makes every overlap test
        # against it fail. Give runs a nominal thickness centred on the pipe.
        if kind == "run":
            if h < _RUN_THICKNESS:
                y0 -= (_RUN_THICKNESS - h) / 2
                h = _RUN_THICKNESS
            if w < _RUN_THICKNESS:
                x0 -= (_RUN_THICKNESS - w) / 2
                w = _RUN_THICKNESS
        out.append(
            SymbolRegion(
                bbox=[round(x0, 5), round(y0, 5), round(w, 5), round(h, 5)],
                kind=kind,
            )
        )
    return out


def assign_regions(
    entities: list[dict],
    regions: list[SymbolRegion],
    radius: float = 0.09,
) -> list[dict]:
    """Snap each tag's bbox from its text box to the symbol it labels.

    A tag is drawn next to the thing it names, not on top of it: equipment
    tags sit under the box, line tags sit above the run. Scoring prefers a
    region that contains the text, then a nearby region whose shape matches
    the type the grammar inferred.
    """
    if not regions:
        return entities
    taken: set[int] = set()
    # Instruments first: their text sits inside the bubble, so those matches
    # are unambiguous and should claim their region before anything else.
    order = sorted(
        range(len(entities)),
        key=lambda i: 0 if entities[i].get("type") == "instrument" else 1,
    )

    for idx in order:
        ent = entities[idx]
        bbox = ent.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        tx, ty = bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2
        want = _TYPE_TO_KIND.get(ent.get("type", ""), "")

        best_i, best_score = None, 0.0
        for i, region in enumerate(regions):
            if i in taken:
                continue
            d = math.hypot(tx - region.cx, ty - region.cy)
            if d > radius:
                continue
            score = 1.0 - (d / radius)
            if region.contains(tx, ty):
                score += 1.0
            if want and region.kind == want:
                score += 0.75
            elif want:
                score -= 0.35
            if score > best_score:
                best_i, best_score = i, score

        if best_i is None:
            continue
        taken.add(best_i)
        region = regions[best_i]
        ent["text_bbox"] = list(bbox)
        ent["bbox"] = list(region.bbox)
        ent["symbol_kind"] = region.kind
        # A tag that landed on a shape of the expected kind corroborates the
        # grammar's type; say so rather than leaving it implicit.
        if want and region.kind == want:
            ent["confidence"] = round(min(0.99, float(ent.get("confidence", 0.8)) + 0.02), 3)
    return entities


def _is_noise(text: str) -> bool:
    upper = re.sub(r"[^A-Z0-9 ]", " ", text.upper()).strip()
    head = upper.split(" ")[0] if upper else ""
    return head in _STOPWORDS


def entities_from_text(items: Iterable[TextItem]) -> list[dict]:
    """Turn a text layer into typed entity dicts via the ISA-5.1 grammar."""
    found: dict[str, dict] = {}
    for item in items:
        text = item.text.strip()
        if _is_noise(text) or not looks_like_tag(text):
            continue
        parsed: ParsedTag = parse_tag(text)
        if not parsed.valid or not parsed.canonical:
            continue
        # Exact vector text + a tag that satisfies the grammar is the highest
        # confidence this pipeline can produce without a human.
        confidence = round(min(0.99, 0.85 + parsed.grammar_confidence * 0.14), 3)
        candidate = {
            "type": parsed.entity_type,
            "tag": parsed.canonical,
            "label": parsed.as_label(),
            "raw_text": text,
            "bbox": [round(v, 5) for v in item.bbox],
            "confidence": confidence,
            "source_layer": "vector-text",
        }
        if parsed.line_size_mm:
            candidate["line_size_mm"] = parsed.line_size_mm
        prior = found.get(parsed.canonical)
        if prior is None or candidate["confidence"] > prior["confidence"]:
            found[parsed.canonical] = candidate
    return list(found.values())


def extract(pdf_page) -> Optional[dict]:
    """Full vector extraction for one page, or None when there is no text layer."""
    if not has_vector_text(pdf_page):
        return None
    text_items = words(pdf_page)
    ents = entities_from_text(text_items)
    if not ents:
        return None
    regions = shapes(pdf_page)
    ents = assign_regions(ents, regions)
    return {
        "entities": ents,
        "relationships": [],
        "_segments": segments(pdf_page),
        "_regions": regions,
        "_text_items": text_items,
    }
