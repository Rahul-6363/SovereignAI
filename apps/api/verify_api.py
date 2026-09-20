"""Self-contained verification: boots the API, runs smoke_test.py, and prints
the server's own traceback if any request fails. No PowerShell involved."""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
LOG = HERE / "_server.log"

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app",
     "--port", "8010", "--log-level", "warning"],
    cwd=HERE, stdout=open(LOG, "w", encoding="utf-8"),
    stderr=subprocess.STDOUT,
)
try:
    src = (HERE / "smoke_test.py").read_text(encoding="utf-8")
    try:
        exec(src)
        print("== verification PASSED ==")
    except (SystemExit, AssertionError) as e:
        print(f"== verification FAILED: {e} ==")
        time.sleep(1)
        print("--- server log tail ---")
        print(LOG.read_text(encoding="utf-8")[-4000:])
        sys.exit(1)
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
