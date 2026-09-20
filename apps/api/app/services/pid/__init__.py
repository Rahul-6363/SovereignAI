"""P&ID extraction pipeline (README §4.5).

Layered, so accuracy does not depend on one vision-model call:

    vector_layer  — exact text + geometry from born-digital PDFs (no model)
    tiling        — overlapping tiled VLM passes for raster / scanned sheets
    tag_grammar   — ISA-5.1 tag parsing; turns raw text into typed entities
    topology      — geometric association of instruments/valves/lines
    rules         — engineering validation; violations become NEEDS_REVIEW
"""
