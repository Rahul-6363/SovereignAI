"""Boot check: proves uvicorn --reload starts cleanly after the fix.

Tests BOTH launch styles on scratch ports:
  1. python -m uvicorn ... --reload   (the documented fix — must work)
  2. uvicorn ... --reload             (console script — works after upgrade)
"""
import subprocess
import sys
import time
import urllib.request


def boot_ok(cmd, port, log_name):
    log = open(log_name, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    ok = False
    for _ in range(60):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=2
            ).read()
            ok = True
            break
        except Exception:
            time.sleep(0.5)
    time.sleep(1)
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()
    return ok


ok1 = boot_ok(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8022", "--reload"],
    8022, "_boot1.log",
)
print(f"python -m uvicorn --reload : {'BOOT OK' if ok1 else 'BOOT FAILED'}")

ok2 = boot_ok(
    ["uvicorn", "app.main:app", "--port", "8023", "--reload"],
    8023, "_boot2.log",
)
print(f"uvicorn (console) --reload : {'BOOT OK' if ok2 else 'BOOT FAILED'}")

if not ok1:
    print("--- python -m boot log tail ---")
    print(open("_boot1.log", encoding="utf-8").read()[-1500:])
if not ok2:
    print("--- console-script boot log tail ---")
    print(open("_boot2.log", encoding="utf-8").read()[-1500:])

sys.exit(0 if ok1 else 1)
