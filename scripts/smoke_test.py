"""End-to-end API smoke test using FastAPI TestClient.

Covers: projects -> upload -> ingest -> status polling -> entities ->
graph -> search -> SSE chat stream. Run from repo root:
    python scripts/smoke_test.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.config import get_settings  # noqa: E402

settings = get_settings()
FAILURES = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def collect_sse(resp) -> list:
    events = []
    lines = resp.text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("event: "):
            ev = lines[i][7:]
            data = ""
            i += 1
            if i < len(lines) and lines[i].startswith("data: "):
                data = lines[i][6:]
                i += 1
            events.append((ev, data))
        i += 1
    return events
def main() -> int:
    with TestClient(app) as client:
        # ── health ───────────────────────────────────────────
        r = client.get("/api/health")
        check("health", r.status_code == 200, str(r.json().get("status")))

        # ── projects ─────────────────────────────────────────
        r = client.get("/api/projects")
        check("list projects", r.status_code == 200)
        r = client.post("/api/projects", json={"name": f"Smoke Plant {int(time.time())}"})
        pid = r.json()["id"]
        check("project ready", pid is not None, f"project_id={pid}")

        # ── upload demo P&ID ─────────────────────────────────
        pid_path = settings.demo_path / "pid" / "unit-a-pid.png"
        with open(pid_path, "rb") as fh:
            r = client.post(
                f"/api/documents/{pid}/upload",
                files={"file": ("unit-a-pid.png", fh, "image/png")},
            )
        check("upload", r.status_code in (200, 201), str(r.status_code))
        doc_id = r.json()["id"]

        # ── ingest ───────────────────────────────────────────
        r = client.post(f"/api/documents/{doc_id}/ingest")
        check("ingest start", r.status_code == 200)
        st = {}
        for _ in range(80):
            r = client.get(f"/api/documents/{doc_id}/status")
            st = r.json()
            if st["status"] in ("ready", "failed"):
                break
            time.sleep(0.25)
        check("ingest ready", st["status"] == "ready", f"{st['status']}:{st['stage']}")
        check("entities > 0", st["entities"] > 0, f"entities={st['entities']}")
        check("relationships > 0", st["relationships"] > 0, f"rels={st['relationships']}")

        r = client.get(f"/api/documents/{doc_id}/entities")
        tags = {e["canonical_tag"] for e in r.json()}
        check("P-101 extracted", "P-101" in tags, str(sorted(tags)[:8]))
        check("instrument extracted", "PI-102" in tags)

        # ── graph ────────────────────────────────────────────
        r = client.get(f"/api/projects/{pid}/memory/graph")
        g = r.json()
        check("graph nodes", len(g["nodes"]) >= 15, f"nodes={len(g['nodes'])}")
        check("graph edges", len(g["edges"]) >= 10, f"edges={len(g['edges'])}")

        # ── entity detail ────────────────────────────────────
        r = client.get(f"/api/memory/{pid}/entities/P-101")
        check("entity detail", r.status_code == 200)
        check("entity connections", len(r.json()["connections"]) > 0)

        # ── search ───────────────────────────────────────────
        r = client.post(
            f"/api/projects/{pid}/search", json={"query": "instruments P-101"}
        )
        n = len(r.json()["results"])
        check("search", r.status_code == 200 and n > 0, f"result_count={n}")

        # ── chat SSE ─────────────────────────────────────────
        r = client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "Which instruments are associated with P-101?"},
        )
        check(
            "chat stream",
            r.status_code == 200
            and "text/event-stream" in r.headers.get("content-type", ""),
        )
        events = collect_sse(r)
        kinds = [e for e, _ in events]
        for k in ("status", "evidence", "token", "done"):
            check(f"chat has {k} event", k in kinds)
        done = next((json.loads(d) for e, d in events if e == "done"), None)
        check("done has message", bool(done and done["message"]))
        message = "".join(json.loads(d)["text"] for e, d in events if e == "token")
        check("mentions PI-102", "PI-102" in message, message[:120].replace("\n", " "))

        # ── uncertainty question ─────────────────────────────
        r = client.post(
            f"/api/projects/{pid}/chat",
            json={"message": "What connections are uncertain on this page?"},
        )
        events = collect_sse(r)
        text = "".join(json.loads(d)["text"] for e, d in events if e == "token")
        check("uncertainty surfaced", "TT-201" in text or "uncertain" in text.lower(), text[:160])

        # ── trust ────────────────────────────────────────────
        r = client.get("/api/trust/status")
        check("trust status", r.status_code == 200, str(r.json().get("ollama_connected")))
        r = client.get("/api/trust/audit")
        check("audit events", r.status_code == 200 and len(r.json()) > 0, f"n={len(r.json())}")

    print()
    if FAILURES:
        print(f"SMOKE TEST FAILED — {len(FAILURES)} failures: {FAILURES}")
        return 1
    print("SMOKE TEST PASSED — full pipeline works")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())