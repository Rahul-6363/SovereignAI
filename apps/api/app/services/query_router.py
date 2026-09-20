"""Query router — deterministic intent classification.

Intent classes follow README section 16 layer 1:
PID_VISUAL, PLANT_MEMORY, DOCUMENT_SEARCH, GENERAL_CHAT.
A small optional LLM refinement is available but the MVP path is
rule-based so it is deterministic in the demo.
"""
from __future__ import annotations

import re

_TAG_RE = re.compile(r"\b([A-Z]{1,6}[- _]?\d{2,4}[A-Z0-9]?)\b")

_INTENT_RULES = [
    # document search keywords
    (re.compile(r"manual|report|document|sop|procedure|finding|inspection "
                r"|search.*document|in document|from .* pdf", re.I), "DOCUMENT_SEARCH"),
    # show / where / highlight / draw region
    (re.compile(r"\bshow\b|\bhighlight\b|\bwhere is\b|\bwhere's\b|\bon the (pid|drawing|diagram)"
                r"|\bregion\b|\blocation of\b|\bpoint to\b", re.I), "PID_VISUAL"),
    # plant tags / equipment / instruments / valves / lines
    (re.compile(r"\b(instrument|valve|pump|equipment|tank|line|connection|upstream|downstream"
                r"|path|trace|feed|associated|connected|cooling|steam)\b", re.I), "PLANT_MEMORY"),
]

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|thanks|thank you|good morning|good afternoon|good evening)\b", re.I
)


def find_tags(query: str):
    tags = set()
    for m in _TAG_RE.findall(query.upper()):
        tags.add(re.sub(r"[ _]", "-", m))
    return sorted(tags)


def classify(query: str) -> dict:
    tags = find_tags(query)
    if _GREETING_RE.match(query.strip()):
        return {"intent": "GENERAL_CHAT", "confidence": 0.95, "tags": tags}

    best_intent = "GENERAL_CHAT"
    best_confidence = 0.0
    for pattern, intent in _INTENT_RULES:
        m = pattern.search(query)
        if m:
            # give PID_VISUAL a boost when the query explicitly asks to show
            conf = 0.9 if intent in ("PID_VISUAL", "DOCUMENT_SEARCH") else 0.75
            if intent == "PLANT_MEMORY" and tags:
                conf = 0.85
            if conf > best_confidence:
                best_confidence = conf
                best_intent = intent

    if tags and best_intent in ("GENERAL_CHAT", "PID_VISUAL"):
        # A concrete plant tag should be treated as a memory question
        # unless it explicitly requests a location/highlight.
        if " show " not in f" {query.lower()} " and "highlight" not in query.lower():
            best_intent = "PLANT_MEMORY"
            best_confidence = max(best_confidence, 0.9)

    # PID_VISUAL queries also carry a memory component: keep the split visible
    if best_intent == "GENERAL_CHAT" and not tags:
        best_confidence = 0.6

    return {"intent": best_intent, "confidence": best_confidence, "tags": tags}


def choose_model(settings, intent: str, have_tags: bool) -> str:
    """Layer 2 — difficulty based model selection."""
    if intent == "GENERAL_CHAT":
        return settings.ollama_chat_model
    if have_tags and settings.enable_model_escalation and intent == "PLANT_MEMORY":
        return settings.reasoning_fallback_model
    return settings.ollama_chat_model