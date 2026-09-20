"""Overlapping tiled vision extraction (README §4.5 steps 1, 3).

A P&ID sheet is ~1 m wide and carries hundreds of 3 mm tags. Handing the whole
sheet to a 3B vision model in one call downsamples it to roughly 1000 px on the
long edge before the encoder ever sees it, so most tags are a few pixels tall
and simply are not legible. That is the dominant failure mode of the
single-shot path — not the prompt, and not the JSON parsing.

Tiling trades calls for pixels: each tile is encoded at full resolution, so the
same tag arrives 3–6x larger. Tiles overlap, because a tag sitting on a tile
boundary would otherwise be cut in half and read as two fragments; anything
found twice is reconciled by `merge_tiles`.

Cost is real — an NxM grid is N*M model calls — so `plan_tiles` is adaptive:
small or sparse sheets stay on the single-pass path.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

from PIL import Image

from .tag_grammar import parse_tag

# Fraction of a tile shared with its neighbour on each side.
DEFAULT_OVERLAP = 0.12

# Below this long edge a sheet is already legible in one pass.
MIN_EDGE_FOR_TILING = 1400


@dataclass
class Tile:
    """One crop of the page, with the transform back to page coordinates."""

    image: Image.Image
    col: int
    row: int
    # Origin and size of this tile in page fractions (0..1).
    x0: float
    y0: float
    w: float
    h: float

    @property
    def name(self) -> str:
        return f"r{self.row}c{self.col}"

    def to_page_bbox(self, bbox: list[float]) -> list[float]:
        """Tile-local [x,y,w,h] fractions → page fractions."""
        if not bbox or len(bbox) != 4:
            return [0.0, 0.0, 0.0, 0.0]
        x, y, w, h = [float(v) for v in bbox]
        return [
            round(min(max(self.x0 + x * self.w, 0.0), 1.0), 5),
            round(min(max(self.y0 + y * self.h, 0.0), 1.0), 5),
            round(min(max(w * self.w, 0.0), 1.0), 5),
            round(min(max(h * self.h, 0.0), 1.0), 5),
        ]


def plan_tiles(image: Image.Image, grid: str = "auto") -> tuple[int, int]:
    """Decide the tile grid for this page.

    `grid` is "auto", "off"/"1x1", or an explicit "CxR" such as "3x2".
    """
    spec = (grid or "auto").strip().lower()
    if spec in ("off", "none", "1x1"):
        return (1, 1)

    explicit = re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", spec)
    if explicit:
        return (max(1, int(explicit.group(1))), max(1, int(explicit.group(2))))

    # auto: scale the grid with the sheet, capped so cost stays bounded.
    long_edge = max(image.width, image.height)
    if long_edge < MIN_EDGE_FOR_TILING:
        return (1, 1)
    aspect = image.width / max(image.height, 1)
    if long_edge < 2200:
        cols, rows = (2, 2)
    elif long_edge < 3200:
        cols, rows = (3, 2)
    else:
        cols, rows = (3, 3)
    if aspect >= 1.6:  # wide plot sheet: favour horizontal splits
        cols = min(cols + 1, 4)
        rows = max(1, rows - 1)
    return (cols, rows)


def make_tiles(
    image: Image.Image, cols: int, rows: int, overlap: float = DEFAULT_OVERLAP
) -> list[Tile]:
    """Cut the page into an overlapping grid."""
    if cols <= 1 and rows <= 1:
        return [Tile(image=image, col=0, row=0, x0=0.0, y0=0.0, w=1.0, h=1.0)]

    tw, th = 1.0 / cols, 1.0 / rows
    ox, oy = tw * overlap, th * overlap
    tiles: list[Tile] = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0.0, c * tw - ox)
            y0 = max(0.0, r * th - oy)
            x1 = min(1.0, (c + 1) * tw + ox)
            y1 = min(1.0, (r + 1) * th + oy)
            box = (
                int(x0 * image.width),
                int(y0 * image.height),
                int(x1 * image.width),
                int(y1 * image.height),
            )
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            tiles.append(
                Tile(
                    image=image.crop(box),
                    col=c,
                    row=r,
                    x0=round(x0, 5),
                    y0=round(y0, 5),
                    w=round(x1 - x0, 5),
                    h=round(y1 - y0, 5),
                )
            )
    return tiles


def _iou(a: list[float], b: list[float]) -> float:
    """Intersection-over-union of two [x,y,w,h] boxes."""
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ax1, ay1 = ax0 + aw, ay0 + ah
    bx1, by1 = bx0 + bw, by0 + bh
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _union_bbox(a: list[float], b: list[float]) -> list[float]:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    x0, y0 = min(ax0, bx0), min(ay0, by0)
    x1, y1 = max(ax0 + aw, bx0 + bw), max(ay0 + ah, by0 + bh)
    return [round(x0, 5), round(y0, 5), round(x1 - x0, 5), round(y1 - y0, 5)]


def merge_tiles(results: list[dict], iou_threshold: float = 0.25) -> dict:
    """Reconcile per-tile extractions into one page-level extraction.

    Two rules, in order:
      * identical canonical tag  → same physical item; keep the more confident
        reading and, when the boxes overlap, union them (the item straddled a
        tile seam).
      * different tag, high IoU  → two readings of one symbol; keep the one the
        ISA-5.1 grammar accepts, since a well-formed tag beats a noisy one.
    """
    by_tag: dict[str, dict] = {}
    order: list[str] = []

    for result in results:
        for ent in result.get("entities", []) or []:
            tag = ent.get("tag")
            if not tag:
                continue
            prior = by_tag.get(tag)
            if prior is None:
                by_tag[tag] = dict(ent)
                order.append(tag)
                continue
            # Same tag seen in two tiles.
            better = ent if ent.get("confidence", 0) > prior.get("confidence", 0) else prior
            merged = dict(better)
            if _iou(prior.get("bbox", []), ent.get("bbox", [])) > 0:
                merged["bbox"] = _union_bbox(prior["bbox"], ent["bbox"])
            # Agreement across independent tiles is evidence in itself.
            merged["confidence"] = round(
                min(0.99, max(prior.get("confidence", 0), ent.get("confidence", 0)) + 0.03),
                3,
            )
            merged["seen_in_tiles"] = int(prior.get("seen_in_tiles", 1)) + 1
            by_tag[tag] = merged

    entities = [by_tag[t] for t in order]

    # Second pass: collapse different tags that describe the same symbol.
    kept: list[dict] = []
    for ent in sorted(entities, key=lambda e: -float(e.get("confidence", 0))):
        clash = None
        for k in kept:
            if _iou(ent.get("bbox", []), k.get("bbox", [])) >= iou_threshold:
                clash = k
                break
        if clash is None:
            kept.append(ent)
            continue
        if parse_tag(ent["tag"]).valid and not parse_tag(clash["tag"]).valid:
            kept[kept.index(clash)] = ent

    # Relationships: dedupe on the (source, relation, target) triple.
    rels: dict[tuple, dict] = {}
    for result in results:
        for rel in result.get("relationships", []) or []:
            key = (rel.get("source"), rel.get("relation"), rel.get("target"))
            if not all(key):
                continue
            prior = rels.get(key)
            if prior is None or rel.get("confidence", 0) > prior.get("confidence", 0):
                rels[key] = dict(rel)

    tags = {e["tag"] for e in kept}
    return {
        "entities": kept,
        # A relationship whose endpoints did not survive the merge is noise.
        "relationships": [
            r for r in rels.values()
            if r["source"] in tags and r["target"] in tags
        ],
    }


def upscale_for_vlm(image: Image.Image, target_edge: int = 1100) -> Image.Image:
    """Enlarge a small tile so thin strokes survive the encoder's own resize."""
    long_edge = max(image.width, image.height)
    if long_edge >= target_edge:
        return image
    scale = min(2.5, target_edge / max(long_edge, 1))
    if scale <= 1.05:
        return image
    return image.resize(
        (int(image.width * scale), int(image.height * scale)), Image.LANCZOS
    )
