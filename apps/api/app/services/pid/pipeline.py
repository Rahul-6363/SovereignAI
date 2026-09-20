"""P&ID extraction orchestrator (README §4.5).

Chooses and combines the layers for whatever drawing actually arrived, so the
pipeline degrades in quality rather than failing:

    born-digital PDF  → vector text + geometry     (exact, no model, instant)
    raster / scanned  → multi-scale OCR + grammar  (seconds, high recall)
    still thin        → overlapping tiled VLM      (last resort, minutes)
    either            → ISA-5.1 grammar, geometric topology, rule validation
    bundled demo      → hand-verified golden replay (deterministic for a demo)

Each result reports `path`, so the UI and the audit log can state how a given
sheet was read instead of implying every drawing is handled identically.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from PIL import Image

from . import (
    raster_geometry,
    raster_layer,
    rules,
    tiling,
    topology,
    vector_layer,
)
from .tag_grammar import parse_tag


def _regrade_with_grammar(entities: list[dict]) -> list[dict]:
    """Let ISA-5.1 correct the type a vision model guessed.

    A VLM routinely labels PSV-101 "instrument" because it is drawn as a
    circle. The grammar knows PSV is a safety valve, and a parsed tag is
    better evidence than a symbol's shape.
    """
    out: list[dict] = []
    for ent in entities:
        tag = ent.get("tag") or ""
        parsed = parse_tag(tag)
        if not parsed.valid:
            out.append(ent)
            continue
        ent = dict(ent)
        ent["tag"] = parsed.canonical
        if parsed.grammar_confidence >= 0.85 and parsed.entity_type != ent.get("type"):
            ent["type_before_grammar"] = ent.get("type")
            ent["type"] = parsed.entity_type
        if not ent.get("label") or ent["label"] == tag:
            ent["label"] = parsed.as_label()
        if parsed.line_size_mm:
            ent["line_size_mm"] = parsed.line_size_mm
        ent["grammar_valid"] = True
        out.append(ent)
    return out


def _dedupe(entities: list[dict]) -> list[dict]:
    """Collapse repeated tags, preferring the instance on the drawing.

    The same tag legitimately appears twice on a sheet: once on the symbol and
    once in the equipment list or legend. Only the first is a location, so an
    instance snapped to a drawn symbol always beats a more-confident reading
    that is really a table cell.
    """
    def rank(ent: dict) -> tuple:
        return (
            1 if ent.get("symbol_kind") else 0,
            float(ent.get("confidence", 0)),
        )

    best: dict[str, dict] = {}
    for ent in entities:
        tag = ent.get("tag")
        if not tag:
            continue
        prior = best.get(tag)
        if prior is None or rank(ent) > rank(prior):
            best[tag] = ent
    return list(best.values())


async def extract_page(
    page_image: Image.Image,
    *,
    pdf_page=None,
    vision_call: Optional[Callable] = None,
    tile_grid: str = "auto",
    max_tiles: int = 9,
    use_ocr: bool = True,
    min_entities: int = 8,
) -> dict:
    """Run the full pipeline for one page.

    `vision_call` is an async `(PIL.Image) -> {"entities", "relationships"}`.
    Passing None runs the vector/geometry path only, which is what the unit
    tests and the air-gapped-before-model-pull case need.
    """
    layers: list[str] = []
    entities: list[dict] = []
    model_relationships: list[dict] = []
    segments: list = []

    # ── layer 1: vector text + geometry (exact, free) ──
    if pdf_page is not None:
        vector = vector_layer.extract(pdf_page)
        if vector:
            entities.extend(vector["entities"])
            segments = vector.get("_segments") or []
            layers.append("vector-text")

    # ── layer 2: OCR, for every sheet without a usable text layer ──
    # A P&ID is mostly text, and OCR reads text in seconds where a 3B vision
    # model needs minutes per tile and still misses most of it. This runs
    # before the model precisely so the model usually does not have to.
    if use_ocr and len(entities) < min_entities and raster_layer.available():
        ocr_result = raster_layer.extract(page_image)
        if ocr_result and ocr_result["entities"]:
            entities.extend(ocr_result["entities"])
            # Name the engine: Paddle and RapidOCR do not score the same on a
            # dense sheet, so a recall figure without the engine is not one.
            layers.append(f"ocr:{raster_layer.engine_name()}")

            # With the text located, the same pixels can give up the pipe
            # runs and the symbol bodies. Without this a scanned sheet has no
            # geometry at all: every distance is measured from a text label,
            # so connectivity degrades to guessing by proximity.
            if not segments and raster_geometry.available():
                text_regions = ocr_result.get("_text_regions")
                segments = raster_geometry.segments(page_image, text_regions)
                shapes = raster_geometry.symbol_regions(page_image, text_regions)
                if shapes:
                    entities = vector_layer.assign_regions(entities, shapes)
                if segments or shapes:
                    layers.append(
                        f"raster-geometry({len(segments)}seg/{len(shapes)}sym)"
                    )

    # ── layer 3: tiled vision — last resort, and genuinely expensive ──
    tiles_used = 0
    if vision_call is not None and len(entities) < min_entities:
        cols, rows = tiling.plan_tiles(page_image, tile_grid)
        if cols * rows > max_tiles:
            cols, rows = (3, 3) if max_tiles >= 9 else (2, 2)
        tiles = tiling.make_tiles(page_image, cols, rows)
        tiles_used = len(tiles)

        async def _read_tile(tile) -> Optional[dict]:
            try:
                raw = await vision_call(tiling.upscale_for_vlm(tile.image))
            except Exception:
                return None  # one bad tile must not lose the rest of the sheet
            if not raw:
                return None
            remapped = []
            for ent in raw.get("entities", []) or []:
                ent = dict(ent)
                ent["bbox"] = tile.to_page_bbox(ent.get("bbox") or [0, 0, 0, 0])
                ent["source_layer"] = f"vision:{tile.name}"
                remapped.append(ent)
            return {
                "entities": remapped,
                "relationships": raw.get("relationships", []) or [],
            }

        # Tiles are independent, so they go out together. Run serially this is
        # N x single-page latency — the difference between a 4-minute ingest
        # and a 15-minute one on the same hardware.
        gathered = await asyncio.gather(*(_read_tile(t) for t in tiles))
        per_tile = [g for g in gathered if g]

        if per_tile:
            merged = tiling.merge_tiles(per_tile)
            entities.extend(merged["entities"])
            model_relationships = merged["relationships"]
            layers.append(f"vision-tiled({cols}x{rows})")

    entities = _regrade_with_grammar(_dedupe(entities))

    # ── layers 3–4: topology, then engineering validation ──
    relationships = topology.infer(
        entities, segments=segments, model_relationships=model_relationships
    )
    report = rules.validate(entities, relationships)
    entities = rules.apply_review_flags(entities, report)

    return {
        "entities": entities,
        "relationships": relationships,
        "_meta": {
            "path": "+".join(layers) if layers else "none",
            "layers": layers,
            "tiles": tiles_used,
            "ocr_available": raster_layer.available(),
            "ocr_engine": raster_layer.engine_name(),
            "segments": len(segments),
            "validation": report.as_dict(),
            "needs_review_count": len(report.needs_review),
        },
    }
