"""P&ID vision extraction.

Two paths:
1. Live vision path — calls the configured Ollama vision model with the
   page image and the strict JSON schema (vision_extraction prompt v1).
2. Golden/deterministic path — replays the hand-verified `expected/*.json`
   extraction for the bundled demo P&ID. Keeps the demo deterministic and
   fully offline / before model pull.

Both paths go through the same normalization + validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PIL import Image

from app.config import Settings, get_settings
from app.services import audit
from app.services.entity_normalizer import (
    VALID_RELATION_TYPES,
    canonical_bbox,
    normalize_entity_type,
    normalize_tag,
)
from app.services.ollama_gateway import OllamaGateway
from app.services.pid import pipeline as pid_pipeline
from app.services.pid import rules as pid_rules
from app.services.pid import topology as pid_topology
from app.services.pid_parser import encode_image_b64
from packages.prompts import VISION_EXTRACTION_PROMPT, prompt_version

_settings = get_settings()


class ExtractionError(Exception):
    pass


# ── golden path ───────────────────────────────────────────────
def load_golden_extraction(settings: Settings, document_name: str) -> Optional[dict]:
    """Load the hand-verified expected extraction for a demo document."""
    candidate = settings.demo_path / "expected" / "entities.json"
    if not candidate.exists():
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return None
    target = str(data.get("document", ""))
    doc_stem = Path(document_name).stem.lower()
    target_stem = Path(target).stem.lower()
    if document_name.lower() == target.lower() or doc_stem == target_stem:
        return data
    return None


_PLACEHOLDER_TOKENS = {
    "tag", "n/a", "na", "none", "null", "unknown", "?",
    "xx-000", "x-999", "item",
}


def _is_placeholder_tag(tag: str) -> bool:
    """Detect schema-example echoes like 'canonical tag when visible, e.g. P-101'
    that small VLMs parrot back instead of real drawing text."""
    if len(tag) > 40:
        return True
    t = tag.strip().lower()
    if t in _PLACEHOLDER_TOKENS:
        return True
    return any(s in t for s in ("e.g", "example", "when visible", "canonical"))


def _validate_entity(raw: dict) -> Optional[dict]:
    tag = normalize_tag(str(raw.get("tag", "") or ""))
    if not tag or _is_placeholder_tag(tag):
        return None
    bbox = canonical_bbox(raw.get("bbox", [0, 0, 0, 0]))
    etype = normalize_entity_type(str(raw.get("type", "tag")))
    label = str(raw.get("label", "") or "")
    conf = max(0.0, min(1.0, float(raw.get("confidence", 0.5) or 0.5)))
    return {
        "type": etype,
        "tag": tag,
        "label": label or tag,
        "raw_text": str(raw.get("raw_text", "") or ""),
        "bbox": bbox,
        "confidence": conf,
    }


def _validate_relationship(raw: dict) -> Optional[dict]:
    source = normalize_tag(str(raw.get("source", "") or ""))
    target = normalize_tag(str(raw.get("target", "") or ""))
    relation = str(raw.get("relation", "") or "").upper()
    if not source or not target or source == target:
        return None
    if relation not in VALID_RELATION_TYPES:
        guess = relation.replace(" ", "_")
        if guess in VALID_RELATION_TYPES:
            relation = guess
        else:
            return None
    conf = max(0.0, min(1.0, float(raw.get("confidence", 0.5) or 0.5)))
    return {"source": source, "relation": relation, "target": target, "confidence": conf}


def normalize_extraction(raw: dict) -> dict:
    """Validate + repair a raw model/JSON response into a strict contract."""
    entities = []
    seen_tags = set()
    for e in raw.get("entities", []) or []:
        ent = _validate_entity(e)
        if ent and ent["tag"] not in seen_tags:
            seen_tags.add(ent["tag"])
            entities.append(ent)
    relationships = []
    seen_rels = set()
    for r in raw.get("relationships", []) or []:
        rel = _validate_relationship(r)
        if rel:
            key = (rel["source"], rel["relation"], rel["target"])
            if key not in seen_rels:
                seen_rels.add(key)
                relationships.append(rel)
    return {"entities": entities, "relationships": relationships}


def _salvage_truncated(text: str) -> Optional[str]:
    """Close a JSON value that was cut off mid-stream (done_reason 'length').

    Keeps everything up to the last complete object and appends the missing
    closing brackets, turning a truncated array/object into parseable JSON.
    """
    last_obj = text.rfind("}")
    if last_obj == -1:
        return None
    trimmed = text[: last_obj + 1]
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in trimmed:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            if stack:
                stack.pop()
    closers = {"[": "]", "{": "}"}
    return trimmed + "".join(closers[c] for c in reversed(stack))


def _upscale_small(page_image: Image.Image) -> Image.Image:
    """Dense P&IDs need pixels: tiny uploads are upscaled 2x (LANCZOS).

    NOTE: measured on moondream:1.8b this does NOT improve extraction (its
    encoder downsizes internally; upscaling mostly adds noise) — kept at 1x.
    """
    return page_image


class VisionExtractor:
    def __init__(self, settings: Settings, gateway: OllamaGateway):
        self.settings = settings
        self.gateway = gateway

    async def extract_page(
        self,
        page_image: Image.Image,
        document_name: str,
        page_number: int,
        pdf_page=None,
    ) -> dict:
        """Extract entities + relationships for one page.

        `pdf_page` is the source PyMuPDF page when the upload was a PDF. When
        it carries a text layer the layered pipeline reads it directly, which
        is both exact and far faster than asking a vision model to read the
        same tags back out of a rendered image.
        """
        model = self.settings.ollama_vision_model
        page_image = _upscale_small(page_image)
        vision_is_online = False
        if not self.settings.force_offline_extraction:
            try:
                vision_is_online = await self.gateway.model_installed(model)
            except Exception:
                vision_is_online = False

        # Always try the golden path first for known demo documents
        golden = load_golden_extraction(self.settings, document_name)
        if golden:
            audit.record_event(
                user_action="extract",
                model="deterministic-golden",
                result_status="ok" if golden.get("entities") else "empty",
            )
            result = normalize_extraction(golden)
            result["_meta"] = {
                "path": "golden",
                "model": "deterministic-golden",
                "prompt_version": prompt_version("vision_extraction"),
            }
            return result

        # ── layered pipeline (README §4.5) ──
        # Vector text, tiled vision, ISA-5.1 grammar, geometric topology and
        # rule validation. Falls back to the legacy single-shot path below if
        # it finds nothing at all, so no drawing gets worse treatment.
        vision_call = None
        if vision_is_online:
            async def vision_call(tile_image):  # noqa: F811
                try:
                    return await self._live_extract_with_image(tile_image, model)
                except ExtractionError:
                    return None

        if pdf_page is not None or vision_is_online or self.settings.pid_use_ocr:
            try:
                layered = await pid_pipeline.extract_page(
                    page_image,
                    pdf_page=pdf_page,
                    vision_call=vision_call,
                    tile_grid=self.settings.pid_tile_grid,
                    max_tiles=self.settings.pid_max_tiles,
                    use_ocr=self.settings.pid_use_ocr,
                    min_entities=self.settings.pid_min_entities,
                )
            except Exception as exc:
                layered = None
                audit.record_event(
                    user_action="extract", model=model,
                    result_status="failed", tool_name="pid_pipeline",
                )
            if layered and layered["entities"]:
                meta = layered["_meta"]
                audit.record_event(
                    user_action="extract",
                    model=model if "vision" in meta["path"] else "vector-layer",
                    result_status="ok",
                    retrieval_count=len(layered["entities"]) + len(layered["relationships"]),
                )
                meta["prompt_version"] = prompt_version("vision_extraction")
                meta["model"] = model if "vision" in meta["path"] else "vector-layer"
                return layered

        # For non-demo documents, try live vision if the model is available
        if vision_is_online:
            try:
                result = await self._live_extract_with_image(page_image, model)
                if result["entities"]:
                    audit.record_event(
                        user_action="extract",
                        model=model,
                        result_status="ok" if result["entities"] else "empty",
                        retrieval_count=len(result["entities"]) + len(result["relationships"]),
                    )
                    result["_meta"] = {
                        "path": "vision",
                        "model": model,
                        "prompt_version": prompt_version("vision_extraction"),
                    }
                    return result
            except ExtractionError:
                pass  # fall through to the text-listing fallback below

            # JSON mode empty or broken → plain text listing (small VLMs are
            # much stronger at "list what you see" than strict JSON).
            try:
                text_result = await self._live_text_extract(page_image, model)
                if text_result["entities"]:
                    audit.record_event(
                        user_action="extract",
                        model=model,
                        result_status="ok",
                        retrieval_count=len(text_result["entities"]),
                    )
                    text_result["relationships"] = pid_topology.infer(
                        text_result["entities"],
                        model_relationships=text_result.get("relationships"),
                    )
                    report = pid_rules.validate(
                        text_result["entities"], text_result["relationships"]
                    )
                    pid_rules.apply_review_flags(text_result["entities"], report)
                    text_result["_meta"] = {
                        "path": "vision-text",
                        "model": model,
                        "note": "",
                        "validation": report.as_dict(),
                        "needs_review_count": len(report.needs_review),
                        "prompt_version": prompt_version("vision_extraction"),
                    }
                    return text_result
                audit.record_event(
                    user_action="extract",
                    model=model,
                    result_status="empty",
                    retrieval_count=0,
                )
                return {"entities": [], "relationships": [], "_meta": {
                    "path": "vision-empty",
                    "model": model,
                    "note": "vision model returned no readable text",
                    "prompt_version": prompt_version("vision_extraction"),
                }}
            except ExtractionError as exc:
                # Vision model call failed - return empty extraction so ingestion
                # completes without crashing. User can retry after pulling the model.
                audit.record_event(
                    user_action="extract",
                    model=model,
                    result_status="failed",
                    tool_name="vision_extract",
                )
                return {"entities": [], "relationships": [], "_meta": {
                    "path": "vision-failed",
                    "model": model,
                    "note": f"vision extraction failed: {exc}",
                    "prompt_version": prompt_version("vision_extraction"),
                }}

        # No vision model and no golden extraction — return empty result.
        # This lets the ingestion pipeline complete gracefully for any image.
        audit.record_event(
            user_action="extract",
            model="none",
            result_status="skipped",
            tool_name="vision_extract",
        )
        return {"entities": [], "relationships": [], "_meta": {
            "path": "no-vision-model",
            "model": "none",
            "note": f"vision model '{model}' not installed and no golden extraction available; "
                    "upload a P&ID and ensure Ollama + vision model are running to extract entities.",
            "prompt_version": prompt_version("vision_extraction"),
        }}

    async def _live_extract_with_image(self, page_image: Image.Image, model: str) -> dict:
        """Stream a chat completion with an inline image part."""
        try:
            import httpx

            response = await self.gateway._client.post(
                f"{self.gateway.base_url}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    # NOTE: no Ollama "format": "json" here — grammar
                    # constraints make small VLMs emit degenerate JSON.
                    "messages": [
                        {
                            "role": "user",
                            "content": VISION_EXTRACTION_PROMPT,
                            "images": [encode_image_b64(page_image)],
                        }
                    ],
                    "options": {
                        "temperature": 0.1,
                        # 4096 ctx: the image tokens + prompt consume the default
                        # 2048 window, leaving no room for output (done_reason
                        # "length" → truncated JSON → zero entities).
                        # NOTE: keep Ollama's default repeat_penalty (1.1) —
                        # higher values make moondream emit degenerate JSON.
                        "num_ctx": 4096,
                        "num_predict": self.settings.vision_num_predict,
                    },
                },
                timeout=300.0,
            )
            if response.status_code != 200:
                raise ExtractionError(f"Vision endpoint error: HTTP {response.status_code}")
            data = response.json()
            content = (data.get("message") or {}).get("content", "")
            if "error" in data:
                raise ExtractionError(str(data["error"]))
            return self._parse_json_content(content)
        except httpx.HTTPError as exc:
            raise ExtractionError(f"Vision HTTP failure: {exc}") from exc

    async def _live_text_extract(self, page_image: Image.Image, model: str) -> dict:
        """Fallback: ask the model to LIST all visible text, one per line.

        Small VLMs are far better at plain text listing than strict JSON, and
        the lines are converted into label/tag entities afterwards (no bbox).
        """
        prompt = (
            "List every piece of text you can see printed in this P&ID "
            "drawing. One item per line, exactly as printed. Include tag "
            "numbers (like letter-dash-number codes), equipment names and "
            "service names. No numbering, no bullets, no commentary."
        )
        response = await self.gateway._client.post(
            f"{self.gateway.base_url}/api/chat",
            json={
                "model": model,
                "stream": False,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [encode_image_b64(page_image)],
                    }
                ],
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 4096,
                    "num_predict": 1024,
                },
            },
            timeout=300.0,
        )
        if response.status_code != 200:
            raise ExtractionError(f"Vision endpoint error: HTTP {response.status_code}")
        data = response.json()
        if "error" in data:
            raise ExtractionError(str(data["error"]))
        content = (data.get("message") or {}).get("content", "")
        import re

        entities = []
        seen: set[str] = set()
        for line in content.splitlines():
            text = line.strip().strip("-*• ").strip()
            if not text or len(text) < 2 or len(text) > 60:
                continue
            if re.fullmatch(r"[\d\s.,;:()]+", text):
                continue
            if re.search(r"\d", text):
                tag = normalize_tag(text)
            else:
                tag = re.sub(r"\s+", " ", text).upper()
            if not tag or _is_placeholder_tag(tag) or tag in seen:
                continue
            seen.add(tag)
            entities.append({
                "type": normalize_entity_type(text),
                "tag": tag,
                "label": text,
                "raw_text": text,
                "bbox": [0.0, 0.0, 0.0, 0.0],
                "confidence": 0.55,
            })
        return {"entities": entities[:50], "relationships": []}

    def _parse_json_content(self, text: str) -> dict:
        import re

        json_str = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", json_str, re.DOTALL)
        if fenced:
            json_str = fenced.group(1).strip()

        # Small VLMs emit messy output: trailing prose after the JSON object,
        # concatenated objects ("Extra data"), or a bare entity array. Try
        # progressively more forgiving strategies.
        candidates: list[str] = [json_str]
        m = re.search(r"[\[{]", json_str)
        if m:
            # raw_decode parses the FIRST complete JSON value and ignores any
            # trailing "extra data" — the most common small-model failure.
            try:
                val, _ = json.JSONDecoder().raw_decode(json_str[m.start():])
                candidates.insert(0, json.dumps(val))
            except json.JSONDecodeError:
                pass
        brace = re.search(r"\{.*\}", json_str, re.DOTALL)
        if brace:
            candidates.append(brace.group(0))
        bracket = re.search(r"\[.*\]", json_str, re.DOTALL)
        if bracket:
            candidates.append(bracket.group(0))

        raw = None
        last_err: Exception | None = None
        for cand in candidates:
            try:
                raw = json.loads(cand)
                break
            except json.JSONDecodeError as exc:
                last_err = exc
        if raw is None:
            # Output was likely truncated (done_reason "length"): close the
            # brackets at the last complete object and retry.
            salvaged = _salvage_truncated(json_str)
            if salvaged is not None:
                try:
                    raw = json.loads(salvaged)
                except json.JSONDecodeError:
                    pass
        if raw is None:
            raise ExtractionError(
                f"Vision model returned invalid JSON: {last_err}"
            )
        if isinstance(raw, list):
            raw = {"entities": raw, "relationships": []}
        return normalize_extraction(raw)