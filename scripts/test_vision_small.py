def main() -> None:
    import base64
    import json as _json
    import sys
    import time as _time
    import urllib.request

    image_path = sys.argv[1] if len(sys.argv) > 1 else "data/demo/pid/unit-a-pid.png"
    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()

    prompt = (
        "You are a P&ID extraction engine. Look at the piping & instrument "
        "diagram. List every equipment/instrument/valve tag you can read, "
        "with its type and label. Reply with JSON ONLY, no prose:\n"
        '{"entities": [{"tag": "P-101", "type": "pump", "label": "Feed Pump", '
        '"bbox": [x, y, w, h]}], '
        '"relationships": [{"source": "T-100", "relation": "connects_to", '
        '"target": "P-101"}]}'
    )

    payload = _json.dumps({
        "model": "moondream:1.8b",
        "stream": False,
        "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        "options": {"temperature": 0.1, "num_predict": 1024},
    }).encode()

    t0 = _time.perf_counter()
    req = urllib.request.Request(
        "http://localhost:11434/api/chat", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        data = _json.loads(resp.read())
    dt = _time.perf_counter() - t0

    content = (data.get("message") or {}).get("content", "")
    eval_count = data.get("eval_count") or 0
    print(f"wall={dt:.1f}s  gen_tokens={eval_count}  tok/s={eval_count / dt:.1f}")
    print("-" * 60)
    print(content[:1500])


if __name__ == "__main__":
    main()
