"""Tests for the layered P&ID pipeline, calculation engine and agent loop.

These pin the behaviours the product's claims rest on: that tags are parsed
by grammar rather than guessed, that geometry decides connectivity, that the
model cannot produce a number, and that the agent's budgets are enforced.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from app.config import get_settings  # noqa: E402
from app.services.calc_engine import (  # noqa: E402
    CalculationError,
    UnitError,
    calculate,
    convert,
)
from app.services.pid import rules, tiling, topology  # noqa: E402
from app.services.pid.tag_grammar import (  # noqa: E402
    looks_like_tag,
    parse_tag,
    same_loop,
)

SETTINGS = get_settings()


# ── ISA-5.1 tag grammar ───────────────────────────────────────
def test_instrument_tags_decode_to_their_function():
    pi = parse_tag("PI-101")
    assert pi.entity_type == "instrument"
    assert pi.measured_variable == "pressure"
    assert "indicate" in pi.functions

    tic = parse_tag("TIC 102")
    assert tic.canonical == "TIC-102"
    assert tic.measured_variable == "temperature"
    assert set(tic.functions) == {"indicate", "control"}


def test_safety_valves_are_valves_not_instruments():
    """PSV is drawn as a circle; only the grammar knows it is a valve."""
    assert parse_tag("PSV-101").entity_type == "valve"
    assert parse_tag("XV-204").entity_type == "valve"


def test_equipment_and_line_prefixes():
    assert parse_tag("P-101A").entity_type == "equipment"
    assert parse_tag("V-101").entity_type == "equipment"
    assert parse_tag("L-101").entity_type == "process_line"


def test_line_spec_tag_yields_a_size():
    parsed = parse_tag('6"-P-1501-A1A')
    assert parsed.entity_type == "process_line"
    assert parsed.line_size_mm == pytest.approx(152.4, abs=0.1)


def test_noise_is_rejected():
    assert not parse_tag("FOOBAR").valid
    assert not looks_like_tag("hello")
    assert not looks_like_tag("SUCTION")


def test_loop_membership():
    assert same_loop("PT-101", "PIC-101")
    assert not same_loop("PT-101", "TIC-101")


# ── tiling ────────────────────────────────────────────────────
def test_tile_bbox_remaps_into_page_coordinates():
    from PIL import Image

    image = Image.new("RGB", (2000, 1000))
    cols, rows = tiling.plan_tiles(image, "2x1")
    tiles = tiling.make_tiles(image, cols, rows, overlap=0.0)
    right = [t for t in tiles if t.col == 1][0]
    # Centre of the right-hand tile is the centre-right of the page.
    x, y, _, _ = right.to_page_bbox([0.5, 0.5, 0.1, 0.1])
    assert x == pytest.approx(0.75, abs=0.02)
    assert y == pytest.approx(0.5, abs=0.02)


def test_merge_prefers_agreement_across_tiles():
    merged = tiling.merge_tiles([
        {"entities": [{"tag": "P-101", "type": "equipment",
                       "confidence": 0.7, "bbox": [0.30, 0.55, 0.06, 0.06]}]},
        {"entities": [{"tag": "P-101", "type": "equipment",
                       "confidence": 0.8, "bbox": [0.32, 0.56, 0.06, 0.06]}]},
    ])
    assert len(merged["entities"]) == 1
    found = merged["entities"][0]
    assert found["seen_in_tiles"] == 2
    # Two independent sightings is evidence; confidence should not drop.
    assert found["confidence"] >= 0.8


def test_merge_drops_relationships_whose_endpoints_did_not_survive():
    merged = tiling.merge_tiles([
        {"entities": [{"tag": "P-101", "type": "equipment",
                       "confidence": 0.9, "bbox": [0.1, 0.1, 0.05, 0.05]}],
         "relationships": [{"source": "P-101", "relation": "TO",
                            "target": "GHOST-999", "confidence": 0.9}]},
    ])
    assert merged["relationships"] == []


# ── topology ──────────────────────────────────────────────────
def _entity(tag, etype, bbox):
    return {"tag": tag, "type": etype, "bbox": bbox, "confidence": 0.9}


def test_instrument_attaches_to_nearest_host():
    entities = [
        _entity("P-101", "equipment", [0.30, 0.50, 0.08, 0.08]),
        _entity("PI-102", "instrument", [0.33, 0.62, 0.04, 0.04]),
        _entity("V-900", "equipment", [0.90, 0.10, 0.06, 0.06]),
    ]
    edges = topology.infer(entities)
    attached = [
        e for e in edges
        if e["relation"] == "HAS_INSTRUMENT" and e["target"] == "PI-102"
    ]
    assert attached and attached[0]["source"] == "P-101"


def test_relationship_endpoints_must_exist():
    entities = [_entity("P-101", "equipment", [0.3, 0.5, 0.05, 0.05])]
    edges = topology.infer(
        entities,
        model_relationships=[
            {"source": "P-101", "relation": "TO", "target": "NOT-REAL",
             "confidence": 0.9}
        ],
    )
    assert all(e["target"] != "NOT-REAL" for e in edges)


def test_every_edge_records_how_it_was_derived():
    entities = [
        _entity("P-101", "equipment", [0.30, 0.50, 0.08, 0.08]),
        _entity("PI-102", "instrument", [0.33, 0.62, 0.04, 0.04]),
    ]
    edges = topology.infer(entities)
    assert edges and all(e.get("method") for e in edges)


# ── rule validation ───────────────────────────────────────────
def test_dangling_instrument_is_surfaced_not_dropped():
    entities = [_entity("PI-999", "instrument", [0.5, 0.5, 0.03, 0.03])]
    report = rules.validate(entities, [])
    assert "PI-999" in report.needs_review
    rules.apply_review_flags(entities, report)
    assert entities[0]["needs_review"] is True


def test_duplicate_tag_is_an_error():
    entities = [
        _entity("P-101", "equipment", [0.1, 0.1, 0.05, 0.05]),
        _entity("P-101", "equipment", [0.6, 0.6, 0.05, 0.05]),
    ]
    report = rules.validate(entities, [])
    assert any(v.rule == "duplicate_tag" and v.severity == "error"
               for v in report.violations)


def test_low_confidence_is_flagged():
    entities = [{"tag": "T-500", "type": "equipment",
                 "bbox": [0.2, 0.2, 0.05, 0.05], "confidence": 0.3}]
    report = rules.validate(entities, [])
    assert any(v.rule == "low_confidence" for v in report.violations)


# ── born-digital vector extraction (the accuracy claim) ───────
def _vector_assets():
    pdf = SETTINGS.demo_path / "pid" / "unit-a-pid-vector.pdf"
    truth = SETTINGS.demo_path / "expected" / "entities-vector.json"
    return pdf, truth


@pytest.mark.skipif(
    not _vector_assets()[0].exists(),
    reason="run scripts/make_vector_pid.py to generate the vector sheet",
)
def test_vector_pipeline_accuracy():
    """The measured numbers behind the P&ID accuracy claim."""
    import pymupdf
    from PIL import Image

    from app.services.pid import pipeline

    pdf_path, truth_path = _vector_assets()
    doc = pymupdf.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    out = asyncio.run(pipeline.extract_page(image, pdf_page=page, vision_call=None))
    doc.close()

    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    exp_e = {e["tag"] for e in truth["entities"]}
    got_e = {e["tag"] for e in out["entities"]}
    exp_r = {(r["source"], r["relation"], r["target"])
             for r in truth["relationships"]}
    got_r = {(r["source"], r["relation"], r["target"])
             for r in out["relationships"]}

    def f1(exp, got):
        tp = len(exp & got)
        p = tp / len(got) if got else 0.0
        r = tp / len(exp) if exp else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0

    # A born-digital sheet is read exactly; anything less is a regression.
    assert f1(exp_e, got_e) == pytest.approx(1.0, abs=0.01)
    # Connectivity is the harder problem and is held to a lower, honest bar.
    assert f1(exp_r, got_r) >= 0.90
    assert "vector-text" in out["_meta"]["path"]
    assert out["_meta"]["tiles"] == 0, "vector path must not call the model"


# ── deterministic calculation engine ──────────────────────────
def test_pressure_drop_is_physically_sane():
    result = calculate(
        "line_pressure_drop_darcy_weisbach",
        {"flow": {"value": 120, "unit": "m3/h"},
         "diameter": {"value": 150, "unit": "mm"},
         "length": {"value": 84.5, "unit": "m"},
         "density": {"value": 850, "unit": "kg/m3"},
         "viscosity": {"value": 3.2, "unit": "cp"}},
        output_unit="bar",
    )
    assert 0.05 < result.result < 1.0
    assert result.status == "NEEDS_ENGINEERING_REVIEW"
    assert result.intermediate_steps
    assert "FORMULA_WHITELISTED" in result.verification


def test_unknown_operation_is_refused():
    """A model must not be able to invent a calculation."""
    with pytest.raises(CalculationError):
        calculate("exec_shell", {})


def test_dimensional_mismatch_raises_rather_than_coercing():
    with pytest.raises(UnitError):
        calculate("fluid_velocity",
                  {"flow": {"value": 1, "unit": "kg"},
                   "diameter": {"value": 1, "unit": "m"}})


def test_unknown_unit_is_refused():
    with pytest.raises(UnitError):
        calculate("fluid_velocity",
                  {"flow": {"value": 1, "unit": "furlongs"},
                   "diameter": {"value": 1, "unit": "m"}})


def test_missing_input_is_refused():
    with pytest.raises(CalculationError):
        calculate("fluid_velocity", {"flow": {"value": 1, "unit": "m3/h"}})


def test_unit_conversions_round_trip():
    assert convert(1, "bar", "pa") == pytest.approx(1e5)
    assert convert(150, "mm", "m") == pytest.approx(0.15)
    assert convert(100, "c", "k") == pytest.approx(373.15)
    assert convert(120, "m3/h", "m3/s") == pytest.approx(0.03333, abs=1e-4)


def test_every_input_carries_its_source():
    result = calculate(
        "fluid_velocity",
        {"flow": {"value": 120, "unit": "m3/h", "source": "DOC-4412 p.7"},
         "diameter": {"value": 150, "unit": "mm", "source": "PID-1023 L-2201"}},
    )
    sources = {p["source"] for p in result.provenance}
    assert "DOC-4412 p.7" in sources
    assert "PID-1023 L-2201" in sources


# ── agent: classification, budgets and policy ─────────────────
def test_task_classification():
    from app.services.agent import (
        TASK_ANSWER, TASK_CALC, TASK_MOC, TASK_TRACKER, classify_task,
    )

    assert classify_task("Draft an MOC note for CV-104") == TASK_MOC
    assert classify_task("Build a tracker of all instruments") == TASK_TRACKER
    assert classify_task("Compute the pressure drop") == TASK_CALC
    assert classify_task("What is connected to P-101?") == TASK_ANSWER


def test_budget_is_enforced():
    from app.services.agent import AgentBudget

    budget = AgentBudget(max_tool_calls=2)
    assert budget.exhausted() is None
    budget.tool_calls = 2
    assert "tool-call budget" in budget.exhausted()


def test_clearance_gates_write_tools():
    from app.services.agent import PlannedCall, policy_decision

    render = PlannedCall("render_docx", {}, "")
    assert policy_decision(render, "operator")[0] == "deny"
    assert policy_decision(render, "engineer")[0] == "deny"
    assert policy_decision(render, "senior_engineer")[0] == "allow"


def test_unknown_tools_are_not_callable():
    from app.services import tools

    for name in ("exec_shell", "send_email", "http_get"):
        assert name not in tools.REGISTRY


# ── audit chain ───────────────────────────────────────────────
def test_audit_chain_detects_tampering():
    from sqlmodel import Session, select

    from app.db import engine, init_db
    from app.models import AuditEvent
    from app.services import audit

    init_db()
    for i in range(4):
        audit.record_event(user_action="chain-test", tool_name=f"t{i}")

    clean = audit.verify_chain()
    assert clean["ok"] is True, clean

    with Session(engine) as session:
        row = session.exec(
            select(AuditEvent).where(AuditEvent.seq > 1).order_by(AuditEvent.seq)
        ).first()
        original, seq = row.result_status, row.seq
        row.result_status = "TAMPERED"
        session.add(row)
        session.commit()

    broken = audit.verify_chain()
    assert broken["ok"] is False
    assert broken["broken_at"]["seq"] == seq

    with Session(engine) as session:
        row = session.exec(
            select(AuditEvent).where(AuditEvent.seq == seq)
        ).first()
        row.result_status = original
        session.add(row)
        session.commit()

    assert audit.verify_chain()["ok"] is True


# ── raster / OCR path ─────────────────────────────────────────
def test_stacked_bubble_halves_are_rejoined():
    """ISA draws an instrument bubble as two stacked lines.

    Read line by line that is `PT` and `101` — neither is a tag. Without the
    vertical merge every instrument on a scanned sheet is lost, which is
    exactly the failure a real upload showed.
    """
    from app.services.pid.raster_layer import _Box, _merge_stacked

    boxes = [
        _Box("PT", 697, 153, 715, 165, 0.9),   # function letters
        _Box("101", 692, 165, 718, 179, 0.9),  # loop number, directly below
    ]
    merged = _merge_stacked(boxes)
    assert any(b.text == "PT-101" for b in merged)


def test_unrelated_stacked_text_is_not_glued_together():
    """Two labels in a column are not a bubble; the centre test must reject."""
    from app.services.pid.raster_layer import _Box, _merge_stacked

    boxes = [
        _Box("PT", 100, 100, 118, 112, 0.9),
        _Box("101", 400, 114, 426, 128, 0.9),  # same row band, far to the right
    ]
    assert not any(b.text == "PT-101" for b in _merge_stacked(boxes))


def test_orphan_digits_signal_missed_bubbles():
    """The count is what decides whether a costlier tiled OCR pass runs."""
    from app.services.pid.raster_layer import _Box, _orphan_digits

    paired = [_Box("PT", 100, 100, 118, 112, 0.9),
              _Box("101", 98, 113, 124, 127, 0.9)]
    assert _orphan_digits(paired) == 0

    orphaned = paired + [_Box("102", 400, 400, 426, 414, 0.9)]
    assert _orphan_digits(orphaned) == 1


def test_drawing_instance_beats_the_legend_entry():
    """A tag in the equipment list is metadata, not a location.

    Picking by OCR confidence alone put P-101's bbox inside the legend table,
    so the drawing instance — the one snapped to a symbol — must win.
    """
    from app.services.pid.pipeline import _dedupe

    legend = {"tag": "P-101", "type": "equipment", "confidence": 0.95,
              "bbox": [0.74, 0.70, 0.03, 0.02]}
    on_drawing = {"tag": "P-101", "type": "equipment", "confidence": 0.80,
                  "bbox": [0.17, 0.33, 0.04, 0.05], "symbol_kind": "box"}
    kept = _dedupe([legend, on_drawing])
    assert len(kept) == 1
    assert kept[0]["symbol_kind"] == "box"
    assert kept[0]["bbox"][0] < 0.5


def test_raster_layers_are_optional():
    """Missing OCR/OpenCV degrades the pipeline; it must not break it."""
    from app.services.pid import raster_geometry, raster_layer

    assert isinstance(raster_layer.available(), bool)
    assert isinstance(raster_geometry.available(), bool)


# ── OCR engine selection ──────────────────────────────────────
def test_ocr_engine_is_named_not_assumed():
    """Recall figures are only meaningful next to the engine that produced
    them, so the pipeline must report which one ran."""
    from app.services.pid import raster_layer

    name = raster_layer.engine_name()
    assert name in {"paddleocr", "rapidocr", "none"}
    assert (name != "none") == raster_layer.available()


def test_paddle_rows_normalise_to_the_common_shape():
    """PaddleOCR 2.x and 3.x return different structures; both must reduce to
    (quad, text, confidence) so nothing above the engine layer cares."""
    from app.services.pid.raster_layer import _normalise_paddle

    quad = [[0, 0], [10, 0], [10, 5], [0, 5]]
    v2 = _normalise_paddle([[[quad, ("PT-101", 0.97)]]])
    v3 = _normalise_paddle(
        [{"dt_polys": [quad], "rec_texts": ["PT-101"], "rec_scores": [0.97]}]
    )
    assert v2 == v3 == [(quad, "PT-101", 0.97)]
    assert _normalise_paddle(None) == []


# ── ingestion must not block the API ──────────────────────────
def test_ingestion_spawns_off_the_event_loop():
    """Ingestion is CPU-bound. Run on the event loop it starves every other
    request, including the status poll the UI needs to show progress — the
    "upload hangs, then a refresh shows it finished" failure."""
    import inspect

    from app.services.ingestion import IngestionPipeline

    assert not inspect.iscoroutinefunction(IngestionPipeline.spawn), (
        "spawn must be synchronous; awaiting it would reintroduce the block"
    )
    source = inspect.getsource(IngestionPipeline.spawn)
    assert "threading.Thread" in source
    assert "daemon=True" in source


def test_ingest_route_does_not_use_background_tasks():
    """FastAPI runs async BackgroundTasks on the event loop, which is exactly
    what blocked the worker. The route must hand off to a thread instead."""
    import inspect

    from app.routers import documents

    source = inspect.getsource(documents.ingest_document)
    assert "pipeline.spawn" in source
    assert "background_tasks" not in source


# ── "ask anything", including files with no plant evidence ────
def test_file_request_without_plant_subject_takes_the_general_path():
    """"Make a spreadsheet of the top vision models" has no evidence in any
    project, so routing it to TRACKER returns an empty sheet. It must take the
    general path instead — and a plant-subject file request must not."""
    from app.services.agent import (
        TASK_GENERAL_DOC,
        TASK_TRACKER,
        build_plan,
        classify_task,
    )

    general = "generate a excel file of all the top performing vision models"
    assert classify_task(general) == TASK_GENERAL_DOC
    assert [c.tool for c in build_plan(general, TASK_GENERAL_DOC)] == [
        "draft",
        "render_xlsx",
    ]

    plant = "compile a tracker of all instruments on the drawing"
    assert classify_task(plant) == TASK_TRACKER

    prose = "write a report on transformer architectures"
    assert [c.tool for c in build_plan(prose, classify_task(prose))] == [
        "draft",
        "render_docx",
    ]


def test_ungrounded_output_is_labelled_unverified():
    """The project's whole claim is that output is traceable. Content that
    isn't must say so, in the file itself — not only in the UI."""
    from app.services.agent import _general_doc_args, _general_table_args

    table = _general_table_args(
        "top vision models",
        {"title": "T", "columns": ["Model"], "rows": [["ViT"]]},
    )
    assert "UNVERIFIED" in table["citations"][0]["label"]
    assert table["citations"][0]["source_type"] == "model"

    doc = _general_doc_args("a report", {"sections": [{"heading": "H", "body": "B"}]})
    # First, not last: the caveat has to arrive before the content.
    assert doc["sections"][0]["heading"] == "Provenance — UNVERIFIED"


def test_ragged_model_rows_still_fill_the_sheet():
    """A small model ignores the column cap, sends objects instead of arrays
    and truncates rows. Dropping those produced a sheet with headers and no
    data, which is worse than a ragged one."""
    from app.services.agent import _general_table_args

    args = _general_table_args(
        "x",
        {
            "columns": ["Model", "Score", "Year"],
            "rows": [
                ["ViT", "88", "2021", "extra ignored"],   # too long
                ["ConvNeXt"],                              # too short
                {"Model": "Swin", "Score": "91", "Year": "2023"},  # object
                ["", "", ""],                              # empty, dropped
            ],
        },
    )
    assert all(len(r) == 3 for r in args["rows"])
    assert args["rows"][0] == ["ViT", "88", "2021"]
    assert args["rows"][1] == ["ConvNeXt", "", ""]
    assert args["rows"][2] == ["Swin", "91", "2023"]
    assert len(args["rows"]) == 3


def test_truncated_model_json_keeps_its_complete_rows():
    """A local model runs out of token budget mid-structure. Discarding the
    whole reply threw away a good table because its last row was half-written."""
    from app.services.tools import _parse_json_object

    truncated = (
        '```json\n{"title": "T", "columns": ["A", "B"], '
        '"rows": [["x", "1"], ["y", "2"], ["z", "'
    )
    parsed = _parse_json_object(truncated)
    assert parsed is not None
    assert parsed["rows"] == [["x", "1"], ["y", "2"]]

    assert _parse_json_object('{"a": 1}') == {"a": 1}
    assert _parse_json_object("no json at all") is None


def test_draft_is_compute_and_cannot_produce_engineering_numbers():
    """Drafting is model knowledge, so it must not inherit write permission,
    and `calculate` must remain the only route to an engineering number."""
    from app.services.tools import REGISTRY

    assert REGISTRY["draft"].permission == "compute"
    assert REGISTRY["calculate"].permission == "compute"
    assert "UNVERIFIED" in REGISTRY["draft"].description
