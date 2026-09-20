"""Confidence aggregation and calibration helpers."""
from __future__ import annotations

from statistics import fmean

CONFIDENCE_FLOOR = 0.35  # below this, surface uncertainty explicitly


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def merge_confidences(values: list[float]) -> float:
    """Combine several confidence scores (geometric-ish compromise)."""
    vals = [clamp(v) for v in values if v is not None]
    if not vals:
        return 0.0
    if len(vals) == 1:
        return clamp(vals[0])
    # geometric mean discourages one weak link answering confidently
    prod = 1.0
    for v in vals:
        prod *= max(v, 0.001)
    return clamp(prod ** (1.0 / len(vals)))


def answer_confidence(evidence_confidences: list[float], model_willingness: float = 1.0) -> float:
    """Final answer confidence: evidence-driven, capped by retrieval coverage."""
    if not evidence_confidences:
        return CONFIDENCE_FLOOR
    base = merge_confidences(evidence_confidences)
    return clamp(base * clamp(model_willingness))


def is_uncertain(confidence: float) -> bool:
    return confidence < CONFIDENCE_FLOOR