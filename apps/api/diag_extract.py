"""Diagnose live vision extraction on a real uploaded file.

Usage: python diag_extract.py <path-to-image>
Prints the raw model reply, the parsed/normalized result, and timing.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import get_settings
from app.services.ollama_gateway import OllamaGateway
from app.services.pid_parser import load_image
from app.services.vision_extractor import VisionExtractor


async def main() -> None:
    settings = get_settings()
    print("vision model      :", settings.ollama_vision_model)
    print("force_offline     :", settings.force_offline_extraction)
    print("vision_num_predict:", settings.vision_num_predict)

    gateway = OllamaGateway(settings)
    extractor = VisionExtractor(settings, gateway)
    model = settings.ollama_vision_model
    print("model_installed   :", await gateway.model_installed(model))

    img = load_image(Path(sys.argv[1]).read_bytes())
    print("image size        :", img.size)

    t0 = time.perf_counter()
    try:
        # exercise the REAL extract_page decision tree (golden/vision/text)
        result = await extractor.extract_page(img, Path(sys.argv[1]).name, 1)
        print(f"elapsed           : {time.perf_counter() - t0:.1f}s")
        print("entities survived :", len(result["entities"]))
        print("relationships     :", len(result.get("relationships", [])))
        print("_meta             :", result.get("_meta"))
        for e in result["entities"][:15]:
            print("  -", e["type"], "|", e["tag"], "|", e["label"])
    except Exception as exc:
        print(f"elapsed           : {time.perf_counter() - t0:.1f}s")
        print("EXTRACTION FAILED :", type(exc).__name__, exc)

    # probe the text-listing fallback directly
    print("--- raw TEXT-LISTING call ---")
    try:
        tres = await extractor._live_text_extract(img, model)
        print("text-list entities:", len(tres["entities"]))
        for e in tres["entities"][:20]:
            print("  -", e["type"], "|", e["tag"])
    except Exception as exc:
        print("text listing failed:", type(exc).__name__, exc)

    # Also capture the RAW model output for inspection
    print("--- raw model call ---")
    import httpx

    try:
        from app.services.pid_parser import encode_image_b64
        from packages.prompts import VISION_EXTRACTION_PROMPT

        resp = await gateway._client.post(
            f"{gateway.base_url}/api/chat",
            json={
                "model": settings.ollama_vision_model,
                "stream": False,
                "messages": [{
                    "role": "user",
                    "content": VISION_EXTRACTION_PROMPT,
                    "images": [encode_image_b64(img)],
                }],
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 4096,
                    "num_predict": settings.vision_num_predict,
                },
            },
            timeout=600.0,
        )
        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        meta = data.get("meta", {}) or {}
        print("done_reason:", data.get("done_reason"), "| eval tokens:",
              meta.get("eval_count"))
        print("raw content length:", len(content))
        print("RAW CONTENT >>>")
        print(content[:4000])
        Path("_diag_raw.txt").write_text(content, encoding="utf-8")
    except Exception as exc:
        print("raw call failed:", type(exc).__name__, exc)


asyncio.run(main())
