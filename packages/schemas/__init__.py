"""
Shared TypeScript/JSON contracts for the Meshcore UI.
Kept in sync with packages/schemas/extraction.schema.json.
"""

EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["type", "tag", "label", "bbox", "confidence"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "equipment", "instrument", "valve", "process_line",
                            "tag", "area", "plant",
                        ],
                    },
                    "tag": {"type": "string", "pattern": "^[A-Z0-9]+[-_][0-9]+$"},
                    "label": {"type": "string"},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "raw_text": {"type": "string"},
                },
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source", "relation", "target", "confidence"],
                "properties": {
                    "source": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": [
                            "HAS_TAG", "CONNECTED_TO", "FLOWS_TO", "FROM", "TO",
                            "HAS_INSTRUMENT", "HAS_VALVE", "MENTIONED_IN",
                            "SUPPORTED_BY", "HAS_FINDING", "HAS_SOP",
                        ],
                    },
                    "target": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
    },
    "required": ["entities", "relationships"],
}

# Evidence packet item shapes (mirrors backend EvidenceSource model)
EVIDENCE_SOURCE_KINDS = ["graph", "pid", "document", "chunk", "memory"]

# Chat SSE event names shared by backend and frontend
CHAT_EVENTS = {
    "STATUS": "status",
    "EVIDENCE": "evidence",
    "TOKEN": "token",
    "TOOL": "tool",  # typed tool call in the agent loop (Phase 1)
    "DONE": "done",
    "DONE_META": "done_meta",
    "ERROR": "error",
}