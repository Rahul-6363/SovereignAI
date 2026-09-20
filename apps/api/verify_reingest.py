"""Verify the extraction fix end-to-end on a throwaway DB copy.

Boots a private API instance (port 8015) with the NEW code, pointed at a
copy of the real database, re-ingests document 21 (images.jpg), and prints
the resulting entity/memory counts. The live API is never touched.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"D:/SIH_fixed/SIH")
API = ROOT / "apps" / "api"
VDB = API / "_verify.db"
VDATA = API / "_verify_data"

shutil.copyfile(ROOT / "data" / "plant_memory.db", VDB)
for sub in ("uploads", "pages", "indexes"):
    (VDATA / sub).mkdir(parents=True, exist_ok=True)

env = os.environ.copy()
env["PYTHONPATH"] = str(API)
env["DATABASE_URL"] = f"sqlite:///{VDB.as_posix()}"
env["UPLOAD_DIR"] = str(VDATA / "uploads")
env["PAGE_DIR"] = str(VDATA / "pages")
env["INDEX_DIR"] = str(VDATA / "indexes")

log = open(API / "_verify_api.log", "w", encoding="utf-8")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8015",
     "--log-level", "warning"],
    cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(
                "http://127.0.0.1:8015/api/health", timeout=2).read()
            break
        except Exception:
            time.sleep(0.5)
    else:
        print("private API never became ready")
        sys.exit(1)
    print("private API ready (fresh code, throwaway DB copy)")

    req = urllib.request.Request(
        "http://127.0.0.1:8015/api/documents/21/ingest", method="POST")
    urllib.request.urlopen(req, timeout=60).read()
    print("re-ingest of doc 21 triggered (moondream on CPU: ~90-150s)")

    deadline = time.time() + 330
    status = None
    while time.time() < deadline:
        time.sleep(5)
        try:
            status = json.loads(urllib.request.urlopen(
                "http://127.0.0.1:8015/api/documents/21/status",
                timeout=10).read())
        except Exception:
            continue
        print(f"  status={status['status']} stage={status['stage']} "
              f"entities={status['entities']}", flush=True)
        if status["status"] in ("ready", "failed"):
            break

    c = sqlite3.connect(VDB)
    n = c.execute(
        "SELECT COUNT(*) FROM entities WHERE document_id=21").fetchone()[0]
    print(f"ENTITIES IN DB for images.jpg (doc 21): {n}")
    for row in c.execute(
        "SELECT entity_type, canonical_tag, label, round(confidence,2) "
        "FROM entities WHERE document_id=21 ORDER BY id LIMIT 15"
    ):
        print("   -", row)
    mem = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    ch = c.execute(
        "SELECT COUNT(*) FROM chunks WHERE document_id=21").fetchone()[0]
    err = c.execute("SELECT error FROM documents WHERE id=21").fetchone()[0]
    print(f"memories total: {mem} | chunks for doc 21: {ch}")
    print(f"doc.error: {err!r}")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()
