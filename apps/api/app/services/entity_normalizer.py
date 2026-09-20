"""Canonical industrial tag / entity type normalization."""

import re

# ── canonical tag normalization ───────────────────────────────
_TAG_SCHEMES = {
    "P": "equipment",
    "E": "equipment",       # heat exchanger
    "T": "equipment",       # tank (unless TIC/T…)
    "V": "equipment",       # vessel
    "C": "equipment",       # compressor / column
    "F": "equipment",       # fan / filter
    "PI": "instrument",
    "TI": "instrument",
    "TIC": "instrument",
    "LIC": "instrument",
    "PIC": "instrument",
    "FIC": "instrument",
    "FT": "instrument",
    "PT": "instrument",
    "TT": "instrument",
    "LT": "instrument",
    "PSV": "valve",
    "PRV": "valve",
    "XV": "valve",
    "HV": "valve",
    "FV": "valve",
    "LV": "valve",
    "TV": "valve",
    "L": "process_line",
    "PL": "process_line",
    "W": "process_line",
    "SL": "process_line",
}


def normalize_tag(raw_tag: str) -> str:
    """Normalize an industrial tag to a canonical form.

    Examples:
        "P-101"  -> "P-101"
        "PI 101" -> "PI-101"
        "L101"   -> "L-101"
        "tic 102"-> "TIC-102"
        "P-101A" -> "P-101A"
    """
    if not raw_tag:
        return raw_tag
    token = raw_tag.strip().upper().replace(" ", "").replace("_", "-")
    m = re.match(r"^([A-Z]+)(?:-)?(\d[\w]*)$", token)
    if m:
        token = f"{m.group(1)}-{m.group(2)}"
    token = re.sub(r"-+", "-", token)
    return token


def canonical_bbox(bbox) -> list[float]:
    """Validate and normalize a bounding box to 0..1 floats."""
    if not bbox or len(bbox) != 4:
        return [0.0, 0.0, 0.0, 0.0]
    out = [max(0.0, min(1.0, float(v))) for v in bbox]
    return out


def type_hint_from_tag(tag: str, fallback: str = "tag") -> str:
    """Guess the entity type from a normalized tag prefix."""
    base = tag.split("-")[0] if "-" in tag else tag.split()[0].upper()
    # longest-prefix match first
    for prefix in sorted(_TAG_SCHEMES, key=len, reverse=True):
        if base.startswith(prefix):
            return _TAG_SCHEMES[prefix]
    return fallback


def normalize_entity_type(raw_type: str) -> str:
    """Map a noisy vision-model type to one of the MVP ontology types."""
    t = (raw_type or "").strip().lower().replace(" ", "_")
    mapping = {
        "equipment": "equipment",
        "equip": "equipment",
        "pump": "equipment",
        "tank": "equipment",
        "vessel": "equipment",
        "compressor": "equipment",
        "heatexchanger": "equipment",
        "heat_exchanger": "equipment",
        "column": "equipment",
        "instrument": "instrument",
        "sensor": "instrument",
        "transmitter": "instrument",
        "gauge": "instrument",
        "indicator": "instrument",
        "valve": "valve",
        "control_valve": "valve",
        "valves": "valve",
        "line": "process_line",
        "process_line": "process_line",
        "pipe": "process_line",
        "pipeline": "process_line",
        "tag": "tag",
        "annotation": "tag",
        "area": "area",
        "plant": "plant",
        "document": "document",
        "finding": "finding",
        "sop": "sop",
    }
    if t in mapping:
        return mapping[t]
    # Fallback: keyword containment handles noisy multi-word types such as
    # "level transmitter", "pressure gauge", "flow control valve", "piping".
    if "valve" in t:
        return "valve"
    if any(k in t for k in ("transmitter", "gauge", "indicator", "sensor", "switch", "controller", "recorder")):
        return "instrument"
    if any(k in t for k in (
        "pump", "tank", "vessel", "compressor", "exchanger", "column",
        "equipment", "drum", "filter", "fan", "heater", "furnace",
        "condenser", "desalter", "separator", "accumulator", "receiver",
        "boiler", "reboiler", "cooler", "scrubber",
    )):
        return "equipment"
    if any(k in t for k in ("line", "pipe", "duct", "pipeline")):
        return "process_line"
    if "annotation" in t or "label" in t or "text" in t:
        return "tag"
    return "tag"


VALID_ENTITY_TYPES = {
    "plant", "area", "equipment", "instrument", "valve",
    "process_line", "tag", "document", "finding", "sop",
}

VALID_RELATION_TYPES = {
    "HAS_TAG", "CONNECTED_TO", "FLOWS_TO", "FROM", "TO",
    "HAS_INSTRUMENT", "HAS_VALVE", "MENTIONED_IN",
    "SUPPORTED_BY", "HAS_FINDING", "HAS_SOP",
}


def relation_from_source(source_type: str, target_type: str) -> str:
    """Suggest a canonical relationship type from the source/target types."""
    if source_type == "equipment" and target_type == "equipment":
        return "CONNECTED_TO"
    if target_type == "instrument":
        return "HAS_INSTRUMENT"
    if target_type == "valve":
        return "HAS_VALVE"
    if source_type == "process_line" or target_type == "process_line":
        return "CONNECTED_TO"
    return "CONNECTED_TO"