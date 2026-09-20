"""OCR text layer for raster / scanned P&IDs (README §4.5 step 2).

The vector layer only fires on born-digital PDFs. Everything else — a scan, a
photo, a PNG exported from a drawing package — used to fall straight through
to the vision model, which on CPU costs minutes per tile and still reads
almost nothing off a dense sheet.

But a P&ID is overwhelmingly *text*: tags, line numbers, service labels. OCR
reads that text in seconds with far better fidelity than a 3B VLM, and the
ISA-5.1 grammar then turns it into typed entities. The vision model is left
for what it is actually good at — describing symbols OCR cannot read.

The one P&ID-specific thing OCR does not do for you is the instrument bubble:
ISA draws it as two stacked lines, the function letters above the loop number.
Read line by line that is `PT` and `101`, neither of which is a tag.
`_merge_stacked` is what turns them back into `PT-101`, and without it every
instrument on the sheet is lost.

OCR is an optional dependency. If it is not installed this module reports
`available() is False` and the pipeline carries on with the vision path.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Optional

from PIL import Image

from .tag_grammar import looks_like_tag, parse_tag
from .vector_layer import TextItem, _STOPWORDS

# Engine handle, built once — model load costs ~1 s and is pure overhead
# on every page after the first.
_ENGINE = None
_ENGINE_TRIED = False
_ENGINE_NAME = "none"

# OCR loses thin strokes on small sheets; enlarging first is cheap and the
# boxes scale back exactly.
MIN_OCR_EDGE = 1800
MAX_OCR_EDGE = 3200

# A digit run sitting this close beneath function letters is the same bubble.
_STACK_GAP_RATIO = 1.4
# Horizontal-centre agreement required before two lines are one bubble.
_STACK_CENTRE_RATIO = 0.75

_LETTERS_RE = re.compile(r"^[A-Z]{1,5}$")
_DIGITS_RE = re.compile(r"^\d{1,5}[A-Z]?$")


def available() -> bool:
    """True when an OCR engine can be loaded."""
    return _engine() is not None


def engine_name() -> str:
    """Which OCR engine is actually in use — reported in `_meta.path`.

    Worth surfacing: the two engines do not score the same on a dense sheet,
    so a recall figure is only meaningful alongside the engine that produced
    it.
    """
    _engine()
    return _ENGINE_NAME


def _load_paddle():
    """PaddleOCR, normalised to `(quad, text, confidence)` triples.

    Paddle detects small, thin, rotated text on dense drawings noticeably
    better than the ONNX default, which is most of the tag text on a P&ID.
    It costs a heavier install and a slower first call (model load), so it is
    preferred when present rather than required.

    The 2.x and 3.x APIs differ in both call and return shape, so both are
    handled here and nothing above this function needs to know which is
    installed.
    """
    from paddleocr import PaddleOCR

    try:  # 3.x: angle classification was renamed
        reader = PaddleOCR(use_textline_orientation=True, lang="en")
    except (TypeError, ValueError):  # 2.x
        reader = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    def run(array):
        try:
            raw = reader.predict(array)  # 3.x
        except AttributeError:
            raw = reader.ocr(array, cls=True)  # 2.x
        return _normalise_paddle(raw)

    return run


def _normalise_paddle(raw) -> list[tuple]:
    """Flatten either PaddleOCR return shape into (quad, text, confidence)."""
    out: list[tuple] = []
    if not raw:
        return out

    for page in raw:
        # 3.x returns dicts keyed by parallel lists.
        if isinstance(page, dict):
            polys = page.get("dt_polys") or page.get("rec_polys") or []
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            for i, text in enumerate(texts):
                quad = polys[i] if i < len(polys) else None
                score = scores[i] if i < len(scores) else 0.0
                if quad is not None:
                    out.append((quad, text, score))
            continue
        # 2.x returns [[quad, (text, score)], ...] per page.
        for line in page or []:
            try:
                quad, payload = line[0], line[1]
                text, score = payload[0], payload[1]
            except (IndexError, TypeError, ValueError):
                continue
            out.append((quad, text, score))
    return out


def _load_rapid():
    """RapidOCR (ONNX) — light, dependency-free, the offline default."""
    from rapidocr_onnxruntime import RapidOCR

    reader = RapidOCR()

    def run(array):
        result, _ = reader(array)
        return [
            (record[0], record[1], record[2])
            for record in (result or [])
            if len(record) >= 3
        ]

    return run


# Preference order. Paddle reads dense drawing text better; Rapid is the
# dependable fallback and keeps the air-gapped install small.
_LOADERS = (("paddleocr", _load_paddle), ("rapidocr", _load_rapid))


def _engine():
    """Load the best available OCR engine once and cache it."""
    global _ENGINE, _ENGINE_TRIED, _ENGINE_NAME
    if _ENGINE_TRIED:
        return _ENGINE
    _ENGINE_TRIED = True

    preferred = os.environ.get("MESHCORE_OCR_ENGINE", "").strip().lower()
    loaders = list(_LOADERS)
    if preferred:
        # An explicit choice wins, but a broken explicit choice still falls
        # back rather than leaving the sheet to the vision model.
        loaders.sort(key=lambda item: item[0] != preferred)

    for name, loader in loaders:
        try:
            _ENGINE = loader()
            _ENGINE_NAME = name
            return _ENGINE
        except Exception:
            continue

    _ENGINE, _ENGINE_NAME = None, "none"
    return _ENGINE


@dataclass
class _Box:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    confidence: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def _prepare(image: Image.Image) -> tuple[Image.Image, float]:
    """Upscale small sheets so thin tag text survives detection."""
    long_edge = max(image.width, image.height)
    if long_edge >= MIN_OCR_EDGE:
        return image, 1.0
    scale = min(MAX_OCR_EDGE / long_edge, MIN_OCR_EDGE / long_edge, 2.5)
    if scale <= 1.05:
        return image, 1.0
    resized = image.resize(
        (int(image.width * scale), int(image.height * scale)), Image.LANCZOS
    )
    return resized, scale


def _run_ocr(image: Image.Image, scale: float, offset: tuple[float, float]
             ) -> list[_Box]:
    """One OCR pass, with its boxes mapped back to original page pixels."""
    engine = _engine()
    if engine is None:
        return []
    try:
        import numpy as np

        result = engine(np.array(image))
    except Exception:
        return []
    if not result:
        return []

    ox, oy = offset
    boxes: list[_Box] = []
    for record in result:
        try:
            quad, text, confidence = record[0], str(record[1]), float(record[2])
        except (IndexError, TypeError, ValueError):
            continue
        text = text.strip()
        if not text:
            continue
        xs = [float(p[0]) / scale + ox for p in quad]
        ys = [float(p[1]) / scale + oy for p in quad]
        boxes.append(_Box(text, min(xs), min(ys), max(xs), max(ys), confidence))
    return boxes


def _dedupe_boxes(boxes: list[_Box]) -> list[_Box]:
    """Drop the same reading found by more than one pass."""
    kept: list[_Box] = []
    for box in sorted(boxes, key=lambda b: -b.confidence):
        duplicate = False
        for other in kept:
            if other.text.upper() != box.text.upper():
                continue
            tol = max(other.height, box.height, 4.0)
            if abs(other.cx - box.cx) < tol and abs(other.cy - box.cy) < tol:
                duplicate = True
                break
        if not duplicate:
            kept.append(box)
    return kept


def _orphan_digits(boxes: list[_Box]) -> int:
    """Digit runs with no function letters above them.

    Each one is an instrument bubble whose letters the detector missed, so
    this is a direct, self-reported measure of how much was lost — and the
    signal used to decide whether a costlier tiled pass is worth running.
    """
    letters = [b for b in boxes if _LETTERS_RE.match(b.text.upper())]
    orphans = 0
    for digits in boxes:
        if not _DIGITS_RE.match(digits.text.upper()):
            continue
        paired = any(
            -letter.height * 0.5 <= digits.y0 - letter.y1
            <= letter.height * _STACK_GAP_RATIO
            and abs(letter.cx - digits.cx)
            <= max(min(letter.width, digits.width), 1.0) * _STACK_CENTRE_RATIO
            for letter in letters
        )
        if not paired:
            orphans += 1
    return orphans


def _read(image: Image.Image, allow_tiles: bool = True) -> list[_Box]:
    """Multi-scale OCR.

    A single pass misses text: at native resolution the detector drops the
    faintest labels, and after upscaling it merges or loses others. The two
    passes fail on *different* text, so their union recovers materially more
    than either alone. A tiled third pass runs only when orphan digits show
    that bubbles are still being missed — it is the expensive one.
    """
    if _engine() is None:
        return []

    boxes = _run_ocr(image, 1.0, (0.0, 0.0))

    prepared, scale = _prepare(image)
    if scale > 1.0:
        boxes += _run_ocr(prepared, scale, (0.0, 0.0))

    boxes = _dedupe_boxes(boxes)

    if allow_tiles and _orphan_digits(boxes) >= 2:
        for tile, offset in _quadrants(image):
            up, tscale = _prepare(tile)
            boxes += _run_ocr(up, tscale, offset)
        boxes = _dedupe_boxes(boxes)
    return boxes


def _quadrants(image: Image.Image, overlap: float = 0.10):
    """Overlapping quarters, so a bubble on a seam is still read whole."""
    w, h = image.width, image.height
    ox, oy = int(w * overlap), int(h * overlap)
    for row in range(2):
        for col in range(2):
            x0 = max(0, col * w // 2 - ox)
            y0 = max(0, row * h // 2 - oy)
            x1 = min(w, (col + 1) * w // 2 + ox)
            y1 = min(h, (row + 1) * h // 2 + oy)
            if x1 - x0 < 16 or y1 - y0 < 16:
                continue
            yield image.crop((x0, y0, x1, y1)), (float(x0), float(y0))


def _merge_stacked(boxes: list[_Box]) -> list[_Box]:
    """Rejoin ISA instrument bubbles split across two lines.

    `PT` drawn above `101` is one tag, not two fragments. Matching is by
    horizontal centre agreement plus a vertical gap proportional to the text
    height, so it survives different bubble sizes on the same sheet without
    gluing together unrelated labels that merely sit in a column.
    """
    letters = [b for b in boxes if _LETTERS_RE.match(b.text.upper())]
    digits = [b for b in boxes if _DIGITS_RE.match(b.text.upper())]
    if not letters or not digits:
        return boxes

    merged: list[_Box] = []
    consumed: set[int] = set()
    for top in letters:
        best: Optional[_Box] = None
        best_index = -1
        best_gap = math.inf
        for i, bottom in enumerate(digits):
            if i in consumed:
                continue
            gap = bottom.y0 - top.y1
            if gap < -top.height * 0.5:
                continue  # the digits are above, not below
            if gap > top.height * _STACK_GAP_RATIO:
                continue
            span = max(min(top.width, bottom.width), 1.0)
            if abs(top.cx - bottom.cx) > span * _STACK_CENTRE_RATIO:
                continue
            if gap < best_gap:
                best, best_index, best_gap = bottom, i, gap
        if best is None:
            continue
        consumed.add(best_index)
        merged.append(
            _Box(
                text=f"{top.text.upper()}-{best.text.upper()}",
                x0=min(top.x0, best.x0),
                y0=min(top.y0, best.y0),
                x1=max(top.x1, best.x1),
                y1=max(top.y1, best.y1),
                confidence=min(top.confidence, best.confidence),
            )
        )
    # Keep the originals too: a bubble half may also be part of a plain label.
    return boxes + merged


def _merge_inline(boxes: list[_Box]) -> list[_Box]:
    """Join `PI` + `101` written side by side on one line."""
    ordered = sorted(boxes, key=lambda b: (round(b.cy, 1), b.x0))
    merged: list[_Box] = []
    for i, left in enumerate(ordered):
        if not _LETTERS_RE.match(left.text.upper()):
            continue
        for right in ordered[i + 1: i + 4]:
            if not _DIGITS_RE.match(right.text.upper()):
                continue
            if abs(right.cy - left.cy) > max(left.height, 1.0) * 0.6:
                continue
            gap = right.x0 - left.x1
            if gap < -left.width * 0.3 or gap > left.height * 1.2:
                continue
            merged.append(
                _Box(
                    text=f"{left.text.upper()}-{right.text.upper()}",
                    x0=min(left.x0, right.x0),
                    y0=min(left.y0, right.y0),
                    x1=max(left.x1, right.x1),
                    y1=max(left.y1, right.y1),
                    confidence=min(left.confidence, right.confidence),
                )
            )
            break
    return boxes + merged


def _is_noise(text: str) -> bool:
    upper = re.sub(r"[^A-Z0-9 ]", " ", text.upper()).strip()
    head = upper.split(" ")[0] if upper else ""
    return head in _STOPWORDS


def _to_text_items(boxes: list[_Box], width: int, height: int) -> list[TextItem]:
    items: list[TextItem] = []
    for b in boxes:
        items.append(
            TextItem(
                text=b.text,
                bbox=[
                    round(max(b.x0, 0) / width, 5),
                    round(max(b.y0, 0) / height, 5),
                    round(min(b.width, width) / width, 5),
                    round(min(b.height, height) / height, 5),
                ],
                confidence=b.confidence,
            )
        )
    return items


def extract(image: Image.Image) -> Optional[dict]:
    """Read a raster P&ID's text layer into typed entities.

    Returns None when OCR is unavailable or the sheet yields no usable tag,
    so the caller can fall back to the vision path.
    """
    boxes = _read(image)
    if not boxes:
        return None

    boxes = _merge_stacked(boxes)
    boxes = _merge_inline(boxes)

    width, height = image.width, image.height
    # Every occurrence is kept, not just the most confident one. A tag printed
    # in the equipment list is often crisper than the same tag on the drawing,
    # so picking by confidence alone locates P-101 inside the legend table.
    # The geometry pass decides which instance sits on a real symbol.
    found: list[dict] = []
    seen: set[tuple] = set()
    for item in _to_text_items(boxes, width, height):
        text = item.text.strip()
        if _is_noise(text) or not looks_like_tag(text):
            continue
        parsed = parse_tag(text)
        if not parsed.valid or not parsed.canonical:
            continue
        # OCR confidence bounds the claim: a crisp reading of a well-formed
        # tag is strong, a marginal one should not look certain.
        confidence = round(
            min(0.97, 0.45 + 0.35 * item.confidence + 0.2 * parsed.grammar_confidence),
            3,
        )
        candidate = {
            "type": parsed.entity_type,
            "tag": parsed.canonical,
            "label": parsed.as_label(),
            "raw_text": text,
            "bbox": item.bbox,
            "confidence": confidence,
            "source_layer": "ocr",
            "ocr_confidence": round(item.confidence, 3),
        }
        if parsed.line_size_mm:
            candidate["line_size_mm"] = parsed.line_size_mm
        key = (
            parsed.canonical,
            round(item.bbox[0], 3),
            round(item.bbox[1], 3),
        )
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)

    if not found:
        return None
    return {
        "entities": found,
        "relationships": [],
        "_text_boxes": len(boxes),
        # Geometry detection needs these to mask characters out before
        # looking for pipes; without the mask every letter becomes a segment.
        "_text_regions": [
            [b.x0 / width, b.y0 / height, b.width / width, b.height / height]
            for b in boxes
        ],
    }
