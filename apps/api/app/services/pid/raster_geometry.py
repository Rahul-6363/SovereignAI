"""Line detection for raster P&IDs (README §4.5 step 4).

A born-digital sheet hands us its pipe geometry directly. A scan does not, so
connectivity on a raster drawing had nothing to work with: the topology layer
fell back to proximity and layout order, which is guesswork.

This recovers the geometry from pixels. The steps are the classical line layer
the README specifies — binarise, suppress text, detect segments, merge
collinear runs — and the output is the same `Segment` type the vector layer
produces, so the topology and rule layers are unchanged.

Two P&ID-specific details matter:

  * **Text must be masked first.** Tag characters are short strokes; left in,
    they generate dozens of phantom two-pixel "pipes" that swamp the real
    ones. The OCR boxes we already have are the mask.
  * **Dash pattern carries meaning.** A broken run is an instrument signal
    lead, not process fluid, and ISA says so. Runs are classified by the gaps
    between their collinear pieces and tagged `dashed`, which is exactly what
    `topology.connect_signal_leads` keys on.

OpenCV is an optional dependency; without it `available()` is False and the
caller keeps the proximity behaviour.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

from PIL import Image

from .vector_layer import Segment, SymbolRegion

_CV2 = None
_CV2_TRIED = False

# Segments shorter than this fraction of the page are noise, not pipes.
MIN_SEGMENT_FRACTION = 0.02
# Collinear pieces closer than this (page fractions) join into one run.
MERGE_GAP = 0.02
# A run whose pieces are separated by more than this is drawn broken.
DASH_GAP = 0.004


def available() -> bool:
    return _cv2() is not None


def _cv2():
    global _CV2, _CV2_TRIED
    if _CV2_TRIED:
        return _CV2
    _CV2_TRIED = True
    try:
        import cv2

        _CV2 = cv2
    except Exception:
        _CV2 = None
    return _CV2


def _mask_text(binary, text_boxes: Iterable[list[float]], w: int, h: int):
    """Paint over text so characters are not detected as pipe segments."""
    cv2 = _cv2()
    for bbox in text_boxes or []:
        if not bbox or len(bbox) != 4:
            continue
        x0 = int(max(bbox[0] * w, 0))
        y0 = int(max(bbox[1] * h, 0))
        x1 = int(min((bbox[0] + bbox[2]) * w, w))
        y1 = int(min((bbox[1] + bbox[3]) * h, h))
        if x1 <= x0 or y1 <= y0:
            continue
        pad = 2
        cv2.rectangle(
            binary,
            (max(x0 - pad, 0), max(y0 - pad, 0)),
            (min(x1 + pad, w), min(y1 + pad, h)),
            0,
            thickness=-1,
        )
    return binary


def _orientation(seg: Segment) -> str:
    dx, dy = abs(seg.x2 - seg.x1), abs(seg.y2 - seg.y1)
    if dx > dy * 4:
        return "h"
    if dy > dx * 4:
        return "v"
    return "d"


def _merge_collinear(segments: list[Segment]) -> list[Segment]:
    """Join pieces of one pipe run, and mark the run dashed if it is broken.

    Hough returns a long pipe as many short colinear pieces; merging them is
    what turns "47 fragments" into "the run from the pump to the exchanger".
    """
    horizontals = [s for s in segments if _orientation(s) == "h"]
    verticals = [s for s in segments if _orientation(s) == "v"]
    others = [s for s in segments if _orientation(s) == "d"]
    merged: list[Segment] = list(others)

    for group, axis in ((horizontals, "h"), (verticals, "v")):
        # Bucket by the constant coordinate, then sweep along the run.
        buckets: dict[int, list[Segment]] = {}
        for seg in group:
            key = round((seg.y1 + seg.y2) / 2 / 0.004) if axis == "h" else \
                  round((seg.x1 + seg.x2) / 2 / 0.004)
            buckets.setdefault(key, []).append(seg)

        for pieces in buckets.values():
            if axis == "h":
                pieces.sort(key=lambda s: min(s.x1, s.x2))
            else:
                pieces.sort(key=lambda s: min(s.y1, s.y2))

            current = pieces[0]
            gaps: list[float] = []
            for nxt in pieces[1:]:
                if axis == "h":
                    cur_end = max(current.x1, current.x2)
                    nxt_start = min(nxt.x1, nxt.x2)
                else:
                    cur_end = max(current.y1, current.y2)
                    nxt_start = min(nxt.y1, nxt.y2)
                gap = nxt_start - cur_end
                if gap <= MERGE_GAP:
                    if gap > DASH_GAP:
                        gaps.append(gap)
                    if axis == "h":
                        xs = [current.x1, current.x2, nxt.x1, nxt.x2]
                        y = (current.y1 + nxt.y1) / 2
                        current = Segment(min(xs), y, max(xs), y,
                                          current.width, current.dashed)
                    else:
                        ys = [current.y1, current.y2, nxt.y1, nxt.y2]
                        x = (current.x1 + nxt.x1) / 2
                        current = Segment(x, min(ys), x, max(ys),
                                          current.width, current.dashed)
                else:
                    current.dashed = len(gaps) >= 2
                    merged.append(current)
                    current, gaps = nxt, []
            current.dashed = len(gaps) >= 2
            merged.append(current)

    return [s for s in merged if s.length >= MIN_SEGMENT_FRACTION]


def segments(
    image: Image.Image,
    text_boxes: Optional[Iterable[list[float]]] = None,
) -> list[Segment]:
    """Detect pipe and signal runs in a raster P&ID, in page fractions."""
    cv2 = _cv2()
    if cv2 is None:
        return []
    try:
        import numpy as np
    except Exception:
        return []

    array = np.array(image.convert("L"))
    h, w = array.shape[:2]
    if h < 32 or w < 32:
        return []

    # Drawings are dark ink on light paper; invert so ink is foreground.
    binary = cv2.adaptiveThreshold(
        array, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )
    binary = _mask_text(binary, text_boxes or [], w, h)

    min_len = int(min(w, h) * MIN_SEGMENT_FRACTION)
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=math.pi / 180,
        threshold=60,
        minLineLength=max(min_len, 12),
        maxLineGap=6,
    )
    if lines is None:
        return []

    raw: list[Segment] = []
    for entry in lines:
        # OpenCV < 5 returns Nx1x4, OpenCV 5 returns Nx4.
        coords = entry[0] if getattr(entry, "ndim", 1) > 1 else entry
        x1, y1, x2, y2 = (float(v) for v in coords)
        seg = Segment(x1 / w, y1 / h, x2 / w, y2 / h, width=0.0, dashed=False)
        if seg.length >= MIN_SEGMENT_FRACTION * 0.5:
            raw.append(seg)

    return _merge_collinear(raw)


# ── symbol regions ────────────────────────────────────────────
# Instrument bubbles are drawn within this fraction of the page edge.
_BUBBLE_MIN_R = 0.008
_BUBBLE_MAX_R = 0.045
# Equipment bodies below this area are noise; above it, page furniture.
_BOX_MIN_AREA = 0.0008
_BOX_MAX_AREA = 0.06


def symbol_regions(
    image: Image.Image,
    text_boxes: Optional[Iterable[list[float]]] = None,
) -> list[SymbolRegion]:
    """Find the drawn symbols on a raster sheet.

    A tag is printed *next to* the thing it names, so without the symbol's own
    extent every distance is measured from a label. On a raster sheet that
    makes a bubble drawn on a pump look no closer to it than to anything else,
    and connectivity collapses.

    Circles are instrument bubbles (Hough); closed rectangular contours are
    equipment bodies. Both are returned in the same `SymbolRegion` shape the
    vector layer produces, so `vector_layer.assign_regions` snaps tags to them
    unchanged.
    """
    cv2 = _cv2()
    if cv2 is None:
        return []
    try:
        import numpy as np
    except Exception:
        return []

    array = np.array(image.convert("L"))
    h, w = array.shape[:2]
    if h < 32 or w < 32:
        return []
    page = float(min(w, h))

    regions: list[SymbolRegion] = []

    # ── instrument bubbles ──
    blurred = cv2.medianBlur(array, 3)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1,
        minDist=int(page * 0.02),
        param1=120, param2=30,
        minRadius=int(page * _BUBBLE_MIN_R),
        maxRadius=int(page * _BUBBLE_MAX_R),
    )
    if circles is not None:
        for c in np.round(circles[0, :]).astype(int):
            cx, cy, r = float(c[0]), float(c[1]), float(c[2])
            regions.append(
                SymbolRegion(
                    bbox=[
                        round(max(cx - r, 0) / w, 5),
                        round(max(cy - r, 0) / h, 5),
                        round(2 * r / w, 5),
                        round(2 * r / h, 5),
                    ],
                    kind="bubble",
                )
            )

    # ── equipment bodies ──
    binary = cv2.adaptiveThreshold(
        array, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )
    binary = _mask_text(binary, text_boxes or [], w, h)
    closed = cv2.morphologyEx(
        binary, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    )
    contours, _ = cv2.findContours(
        closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    page_area = float(w * h)
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = (cw * ch) / page_area
        if not (_BOX_MIN_AREA <= area <= _BOX_MAX_AREA):
            continue
        aspect = cw / max(ch, 1)
        if aspect > 8 or aspect < 0.125:
            continue  # a long thin blob is a pipe run, not a vessel
        regions.append(
            SymbolRegion(
                bbox=[round(x / w, 5), round(y / h, 5),
                      round(cw / w, 5), round(ch / h, 5)],
                kind="box",
            )
        )

    return _dedupe_regions(regions)


def _dedupe_regions(regions: list[SymbolRegion]) -> list[SymbolRegion]:
    """Drop regions that substantially overlap one already kept."""
    kept: list[SymbolRegion] = []
    for region in sorted(regions, key=lambda r: -(r.bbox[2] * r.bbox[3])):
        overlap = False
        for other in kept:
            ax, ay, aw, ah = region.bbox
            bx, by, bw, bh = other.bbox
            ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
            iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
            inter = ix * iy
            smaller = min(aw * ah, bw * bh)
            if smaller > 0 and inter / smaller > 0.6:
                overlap = True
                break
        if not overlap:
            kept.append(region)
    return kept
