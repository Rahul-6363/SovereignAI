"""End-to-end verification for Meshcore.

Answers one question: **is the whole system actually working?**

It exercises every layer in the order a real user meets them, and prints a
PASS/FAIL line per check so a failure names the layer that broke rather than
leaving you to bisect it. Everything runs in-process against a throwaway
database, so it never touches your working data and needs no running server.

    python scripts/verify_e2e.py              # full run
    python scripts/verify_e2e.py --keep       # leave the fixture project behind
    python scripts/verify_e2e.py --quick      # skip the slow ingest

Exit code 0 means every required check passed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

_VERIFY_DB = Path(os.environ.get("TEMP", "/tmp")) / "meshcore-verify" / "verify.db"
_VERIFY_DB.parent.mkdir(parents=True, exist_ok=True)
for suffix in ("", "-wal", "-shm"):
    stale = Path(str(_VERIFY_DB) + suffix)
    if stale.exists():
        stale.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_VERIFY_DB.as_posix()}"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []
SKIPPED: list[tuple[str, str]] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(label)
        print(f"  [PASS] {label}" + (f"  — {detail}" if detail else ""))
    else:
        FAILED.append((label, detail))
        print(f"  [FAIL] {label}" + (f"  — {detail}" if detail else ""))
    return condition


def skip(label: str, why: str) -> None:
    SKIPPED.append((label, why))
    print(f"  [SKIP] {label}  — {why}")


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def sse(client, url: str, payload: dict) -> list[tuple[str, dict]]:
    """Read a POST SSE stream into a list of (event, data)."""
    events: list[tuple[str, dict]] = []
    with client.stream("POST", url, json=payload) as response:
        if response.status_code != 200:
            return [("http_error", {"status": response.status_code})]
        current = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                current = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    events.append((current, json.loads(line[5:])))
                except json.JSONDecodeError:
                    pass
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true",
                        help="keep the fixture project after the run")
    parser.add_argument("--quick", action="store_true",
                        help="skip the document ingest (slowest step)")
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import init_db
    from app.main import app
    from app.services import audit
    from app.services.calc_engine import CalculationError, calculate
    from app.services.pid import pipeline as pid_pipeline

    settings = get_settings()
    init_db()

    print("=" * 66)
    print("MESHCORE END-TO-END VERIFICATION")
    print(f"database: {_VERIFY_DB}")
    print("=" * 66)

    with TestClient(app) as client:
        # ── 1. service is up ──────────────────────────────────
        section("1. Service and model runtime")
        health = client.get("/api/health")
        check("API responds", health.status_code == 200)
        body = health.json() if health.status_code == 200 else {}
        check("local-only mode is on", body.get("local_only") is True,
              "ENABLE_EXTERNAL_NETWORK must be false")
        ollama_up = bool(body.get("ollama"))
        if ollama_up:
            check("Ollama reachable", True, settings.ollama_base_url)
        else:
            skip("Ollama reachable",
                 "not running — the offline paths are still verified below")

        # ── 2. project lifecycle ──────────────────────────────
        section("2. Project lifecycle")
        created = client.post("/api/projects",
                              json={"name": "E2E Verification"})
        check("create project", created.status_code == 201)
        if created.status_code != 201:
            return _summary()
        project_id = created.json()["id"]
        check("read project back",
              client.get(f"/api/projects/{project_id}").status_code == 200,
              f"project {project_id}")

        # ── 3. P&ID pipeline: born-digital vector path ────────
        section("3. P&ID extraction — born-digital vector sheet")
        vector_pdf = settings.demo_path / "pid" / "unit-a-pid-vector.pdf"
        truth_path = settings.demo_path / "expected" / "entities-vector.json"
        if not vector_pdf.exists() or not truth_path.exists():
            skip("vector extraction",
                 "run `python scripts/make_vector_pid.py` first")
        else:
            import asyncio

            import pymupdf
            from PIL import Image

            doc = pymupdf.open(vector_pdf)
            page = doc[0]
            pix = page.get_pixmap(dpi=150)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out = asyncio.run(
                pid_pipeline.extract_page(image, pdf_page=page, vision_call=None)
            )
            doc.close()

            truth = json.loads(truth_path.read_text(encoding="utf-8"))
            exp_e = {e["tag"] for e in truth["entities"]}
            got_e = {e["tag"] for e in out["entities"]}
            exp_r = {(r["source"], r["relation"], r["target"])
                     for r in truth["relationships"]}
            got_r = {(r["source"], r["relation"], r["target"])
                     for r in out["relationships"]}

            def f1(exp: set, got: set) -> float:
                tp = len(exp & got)
                p = tp / len(got) if got else 0.0
                r = tp / len(exp) if exp else 0.0
                return 2 * p * r / (p + r) if (p + r) else 0.0

            symbol_f1, conn_f1 = f1(exp_e, got_e), f1(exp_r, got_r)
            check("vector text layer used",
                  "vector-text" in out["_meta"]["path"], out["_meta"]["path"])
            check("symbol F1 >= 0.90", symbol_f1 >= 0.90, f"F1={symbol_f1:.3f}")
            check("connectivity F1 >= 0.70", conn_f1 >= 0.70, f"F1={conn_f1:.3f}")
            check("ISA-5.1 types assigned",
                  any(e["type"] == "instrument" for e in out["entities"]))
            check("validation rules ran",
                  out["_meta"]["validation"]["violations"] is not None,
                  f"{out['_meta']['needs_review_count']} flagged NEEDS_REVIEW")
            check("no model call needed for this sheet",
                  out["_meta"]["tiles"] == 0,
                  "vector path is exact and free")

        # ── 4. upload + ingest ────────────────────────────────
        section("4. Upload and ingestion")
        demo_png = settings.demo_path / "pid" / "unit-a-pid.png"
        doc_id = None
        ingested = False
        if args.quick:
            skip("ingest a drawing", "--quick")
        elif not demo_png.exists():
            skip("ingest a drawing", "demo P&ID missing")
        else:
            upload = client.post(
                f"/api/documents/{project_id}/upload",
                files={"file": ("unit-a-pid.png", demo_png.read_bytes(),
                                "image/png")},
            )
            check("upload accepted", upload.status_code == 201)
            if upload.status_code == 201:
                doc_id = upload.json()["id"]
                client.post(f"/api/documents/{doc_id}/ingest")
                status = {}
                for _ in range(180):
                    status = client.get(
                        f"/api/documents/{doc_id}/status").json()
                    if status["status"] in ("ready", "failed"):
                        break
                    time.sleep(1)
                check("ingestion reached ready",
                      status.get("status") == "ready",
                      f"stage={status.get('stage')} {status.get('error','')[:60]}")
                ingested = status.get("status") == "ready"
                check("entities extracted", status.get("entities", 0) > 0,
                      f"{status.get('entities')} entities, "
                      f"{status.get('relationships')} links, "
                      f"{status.get('chunks')} chunks")
                check("page image served",
                      client.get(
                          client.get(f"/api/documents/{doc_id}/pages").json()[0]
                          ["image_url"]
                      ).status_code == 200)

        # ── 5. plant memory graph ─────────────────────────────
        section("5. Plant Memory graph")
        graph = client.get(f"/api/projects/{project_id}/memory/graph")
        check("graph endpoint responds", graph.status_code == 200)
        if graph.status_code == 200:
            g = graph.json()
            if ingested:
                check("graph has nodes", len(g["nodes"]) > 0,
                      f"{len(g['nodes'])} nodes, {len(g['edges'])} edges")
            else:
                skip("graph has nodes", "nothing ingested in this run")

        # ── 6. hybrid retrieval ───────────────────────────────
        section("6. Hybrid retrieval")
        search = client.post(f"/api/projects/{project_id}/search",
                             json={"query": "instruments connected to P-101",
                                   "top_k": 8})
        check("search responds", search.status_code == 200)
        if search.status_code == 200:
            payload = search.json()
            if ingested:
                check("results returned", len(payload["results"]) > 0,
                      f"{len(payload['results'])} hits via "
                      f"{payload['evidence'].get('retrieved_from')}")
            else:
                skip("results returned", "nothing ingested in this run")
            check("intent classified", bool(payload["intent"]),
                  payload["intent"])
            check("scores are numeric",
                  all(isinstance(r["score"], (int, float))
                      for r in payload["results"]))

        # ── 7. grounded chat (SSE) ────────────────────────────
        section("7. Grounded chat")
        events = sse(client, f"/api/projects/{project_id}/chat",
                     {"message": "What instruments are connected to P-101?"})
        kinds = [k for k, _ in events]
        check("chat streams", "done" in kinds, f"{len(events)} SSE frames")
        done = next((d for k, d in events if k == "done"), {})
        check("answer is non-empty", bool(done.get("message")),
              (done.get("message") or "")[:60].replace("\n", " "))
        check("evidence attached", "evidence" in kinds)
        check("confidence reported", done.get("confidence", 0) > 0,
              f"{done.get('confidence')}")

        conv_id = next(
            (d.get("conversation_id") for k, d in events
             if k == "status" and d.get("conversation_id")), None)
        if conv_id:
            follow = sse(client, f"/api/projects/{project_id}/chat",
                         {"message": "and what is upstream of it?",
                          "conversation_id": conv_id})
            fdone = next((d for k, d in follow if k == "done"), {})
            check("multi-turn follow-up resolves",
                  bool(fdone.get("message")) and
                  "could not confidently resolve" not in fdone.get("message", ""),
                  "bare follow-up carried the prior tag forward")

        # ── 8. deterministic calculation engine ───────────────
        section("8. Deterministic calculation engine")
        calc = calculate(
            "line_pressure_drop_darcy_weisbach",
            {"flow": {"value": 120, "unit": "m3/h"},
             "diameter": {"value": 150, "unit": "mm"},
             "length": {"value": 84.5, "unit": "m"},
             "density": {"value": 850, "unit": "kg/m3"},
             "viscosity": {"value": 3.2, "unit": "cp"}},
            output_unit="bar",
        )
        check("calculation produces a number", calc.result > 0,
              f"{calc.result} {calc.unit} ({calc.calculation_id})")
        check("working is shown", len(calc.intermediate_steps) >= 3,
              f"{len(calc.intermediate_steps)} steps")
        check("flagged for engineering review",
              calc.status == "NEEDS_ENGINEERING_REVIEW")
        check("inputs carry provenance",
              all(p["source"] for p in calc.provenance))

        blocked = 0
        for label, op, inputs in (
            ("unknown operation", "exec_shell", {}),
            ("dimensional mismatch", "fluid_velocity",
             {"flow": {"value": 1, "unit": "kg"},
              "diameter": {"value": 1, "unit": "m"}}),
            ("unknown unit", "fluid_velocity",
             {"flow": {"value": 1, "unit": "furlongs"},
              "diameter": {"value": 1, "unit": "m"}}),
        ):
            try:
                calculate(op, inputs)
            except CalculationError:
                blocked += 1
        check("invalid calculations refused", blocked == 3, f"{blocked}/3 blocked")

        # ── 9. bounded agent + deliverables ───────────────────
        section("9. Bounded agent and deliverables")
        agent_events = sse(
            client, f"/api/projects/{project_id}/agent",
            {"prompt": "Draft a Management of Change note for replacing "
                       "valve XV-101 with a higher-Cv unit"},
        )
        agent_kinds = [k for k, _ in agent_events]
        check("agent emits a plan", "plan" in agent_kinds)
        check("policy evaluated per call", "policy" in agent_kinds)
        check("typed tools invoked", "tool" in agent_kinds)
        check("verification step ran", "verify" in agent_kinds)

        adone = next((d for k, d in agent_events if k == "agent_done"), {})
        artifacts = adone.get("artifacts", [])
        check("deliverable produced", len(artifacts) > 0,
              artifacts[0]["name"] if artifacts else "none")
        if ingested:
            check("deliverable carries citations",
                  any(a.get("citations", 0) > 0 for a in artifacts),
                  f"{artifacts[0]['citations'] if artifacts else 0} citations")
        else:
            skip("deliverable carries citations",
                 "no ingested sources to cite in this run")
        budget = adone.get("budget", {})
        check("budgets respected",
              budget.get("tool_calls", 99) <= budget.get("max_tool_calls", 12),
              f"{budget.get('tool_calls')}/{budget.get('max_tool_calls')} calls, "
              f"{budget.get('elapsed_s')}s")

        if artifacts:
            name = artifacts[0]["name"]
            dl = client.get(
                f"/api/projects/{project_id}/deliverables/{name}")
            check("deliverable downloads", dl.status_code == 200,
                  f"{len(dl.content)} bytes")
            prov = client.get(
                f"/api/projects/{project_id}/deliverables/{name}/provenance")
            check("provenance sidecar served", prov.status_code == 200,
                  f"{len(prov.json().get('citations', []))} citations")
            check("path traversal refused",
                  client.get(
                      f"/api/projects/{project_id}/deliverables/..%2F..%2Fsecret"
                  ).status_code in (400, 404))

        # clearance policy actually denies
        denied = sse(
            client, f"/api/projects/{project_id}/agent",
            {"prompt": "Draft an MOC note for valve XV-101",
             "clearance": "operator"},
        )
        check("operator clearance denied write",
              any(k == "policy" and d.get("decision") == "deny"
                  for k, d in denied))

        # ── 10. tabular deliverable ───────────────────────────
        section("10. Tabular deliverable")
        tracker = sse(
            client, f"/api/projects/{project_id}/agent",
            {"prompt": "Build a tracker of all instruments with tag and type"},
        )
        tdone = next((d for k, d in tracker if k == "agent_done"), {})
        xlsx = [a for a in tdone.get("artifacts", []) if a["kind"] == "xlsx"]
        check("XLSX tracker produced", len(xlsx) > 0,
              xlsx[0]["name"] if xlsx else "none")

        # ── 11. trust, egress, audit chain ────────────────────
        section("11. Trust, egress and the audit chain")
        trust = client.get("/api/trust/status")
        check("trust status responds", trust.status_code == 200)
        if trust.status_code == 200:
            t = trust.json()
            check("network egress blocked", t["network_egress"] == "Blocked")
            check("no external LLM calls", t["external_llm_calls"] == 0,
                  f"counter = {t['external_llm_calls']}")
            check("audit logging enabled", t["audit_logging"] is True)

        chain = client.get("/api/trust/audit/verify").json()
        check("audit chain verifies", chain.get("ok") is True,
              f"{chain.get('checked')} entries, head seq "
              f"{chain.get('head_seq')}")

        # Prove the chain actually detects tampering rather than always saying OK.
        from sqlmodel import Session, select

        from app.db import engine
        from app.models import AuditEvent

        with Session(engine) as db:
            row = db.exec(
                select(AuditEvent).where(AuditEvent.seq > 1)
                .order_by(AuditEvent.seq)
            ).first()
            if row is None:
                skip("tamper detection", "not enough chained entries")
            else:
                original, seq = row.result_status, row.seq
                row.result_status = "TAMPERED"
                db.add(row)
                db.commit()
                broken = audit.verify_chain()
                detected = (
                    broken.get("ok") is False
                    and (broken.get("broken_at") or {}).get("seq") == seq
                )
                row.result_status = original
                db.add(row)
                db.commit()
                restored = audit.verify_chain().get("ok") is True
                check("tampering detected at the right entry", detected,
                      f"edited seq {seq}")
                check("chain verifies again after restore", restored)

        pack = client.get("/api/trust/evidence-pack")
        check("evidence pack exports", pack.status_code == 200,
              f"{len(pack.json().get('recent_events', []))} events")

        # ── 12. cleanup ───────────────────────────────────────
        section("12. Cleanup")
        if args.keep:
            skip("delete fixture project", "--keep")
        else:
            deleted = client.delete(f"/api/projects/{project_id}")
            check("project deletes cleanly", deleted.status_code == 204)
            check("project is gone",
                  client.get(f"/api/projects/{project_id}").status_code == 404)

    return _summary()


def _summary() -> int:
    total = len(PASSED) + len(FAILED)
    print("\n" + "=" * 66)
    print(f"RESULT: {len(PASSED)}/{total} checks passed"
          + (f", {len(SKIPPED)} skipped" if SKIPPED else ""))
    if FAILED:
        print("\nFailures:")
        for label, detail in FAILED:
            print(f"  - {label}" + (f": {detail}" if detail else ""))
    if SKIPPED:
        print("\nSkipped:")
        for label, why in SKIPPED:
            print(f"  - {label}: {why}")
    print("=" * 66)
    if not FAILED:
        print("Everything required is working end to end.")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
