"""Unit tests: tag normalization, bbox validation, extraction schema,
query routing, confidence, graph memory."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from app.services.entity_normalizer import (  # noqa: E402
    canonical_bbox,
    normalize_entity_type,
    normalize_tag,
    type_hint_from_tag,
)
from app.services.vision_extractor import (  # noqa: E402
    normalize_extraction,
)
from app.services.confidence import (  # noqa: E402
    merge_confidences,
    is_uncertain,
)
from app.services.query_router import classify  # noqa: E402


# ── tag normalization ─────────────────────────────────────────
def test_normalize_tag_variants():
    assert normalize_tag("P-101") == "P-101"
    assert normalize_tag("PI 101") == "PI-101"
    assert normalize_tag("L101") == "L-101"
    assert normalize_tag("tic 102") == "TIC-102"
    assert normalize_tag("P-101A") == "P-101A"


def test_normalize_tag_empty():
    assert normalize_tag("") == ""
    assert normalize_tag(None) is None


def test_type_hint():
    assert type_hint_from_tag("P-101", "tag") == "equipment"
    assert type_hint_from_tag("PI-101", "tag") == "instrument"
    assert type_hint_from_tag("L-101", "tag") == "process_line"
    assert type_hint_from_tag("PSV-101", "tag") == "valve"


def test_normalize_entity_type_mapping():
    assert normalize_entity_type("pump") == "equipment"
    assert normalize_entity_type("level transmitter") == "instrument"
    assert normalize_entity_type("control valve") == "valve"
    assert normalize_entity_type("pipe") == "process_line"


# ── bbox validation ───────────────────────────────────────────
def test_bbox_clamped():
    assert canonical_bbox([-1, 2, 0.5, 3]) == [0.0, 1.0, 0.5, 1.0]


def test_bbox_malformed():
    assert canonical_bbox(None) == [0, 0, 0, 0]
    assert canonical_bbox([1, 2]) == [0, 0, 0, 0]


# ── extraction / JSON schema validation ───────────────────────
def test_normalize_extraction_valid():
    raw = {
        "entities": [
            {"type": "pump", "tag": "P-101", "label": "Pump", "bbox": [0.1, 0.2, 0.3, 0.4], "confidence": 0.9},
            {"type": "instrument", "tag": "PI 101", "label": "Pressure", "bbox": [0.5, 0.5, 0.1, 0.1], "confidence": 0.8},
        ],
        "relationships": [
            {"source": "P-101", "relation": "has_instrument", "target": "PI-101", "confidence": 0.9},
        ],
    }
    out = normalize_extraction(raw)
    assert len(out["entities"]) == 2
    tags = {e["tag"] for e in out["entities"]}
    assert "P-101" in tags and "PI-101" in tags
    assert out["relationships"][0]["relation"] == "HAS_INSTRUMENT"


def test_normalize_extraction_dedupes_and_drops_bad():
    raw = {
        "entities": [
            {"type": "equipment", "tag": "P-101", "label": "", "bbox": [0, 0, 0, 0], "confidence": 0.9},
            {"type": "equipment", "tag": "P-101", "label": "dup", "bbox": [0, 0, 0, 0], "confidence": 0.7},
            {"type": "tag", "tag": "", "label": "", "bbox": None, "confidence": 0.1},
        ],
        "relationships": [
            {"source": "P-101", "relation": "BOGUS", "target": "X-1", "confidence": 0.5},
            {"source": "P-101", "relation": "TO", "target": "P-101", "confidence": 0.5},
        ],
    }
    out = normalize_extraction(raw)
    assert len(out["entities"]) == 1
    assert out["relationships"] == []


# ── confidence ────────────────────────────────────────────────
def test_confidence_merge():
    assert merge_confidences([]) == 0.0
    assert merge_confidences([1.0, 1.0]) == 1.0
    assert merge_confidences([0.9, 0.9]) > 0.85
    assert is_uncertain(0.2) is True
    assert is_uncertain(0.5) is False


# ── query router ──────────────────────────────────────────────
def test_router_intents():
    assert classify("hello there")["intent"] == "GENERAL_CHAT"
    assert classify("What is P-101?")["intent"] == "PLANT_MEMORY"
    assert classify("Show me where P-101 is on the drawing")["intent"] == "PID_VISUAL"
    assert classify("search the inspection manual for pump maintenance")["intent"] == "DOCUMENT_SEARCH"
    assert classify("Which instruments are connected to P-101?")["intent"] == "PLANT_MEMORY"


def test_router_finds_tags():
    r = classify("trace path from L-101 to P-101")
    assert "P-101" in r["tags"]
    assert "L-101" in r["tags"]