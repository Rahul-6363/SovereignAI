"""Smoke test: create → upload → ingest → delete doc → delete project.

Run via verify_api.py, which boots the API on 127.0.0.1:8010 first.
"""
import io
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"
import io
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8010"


def req(method, path, data=None, headers=None):
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]


# wait for health
for _ in range(60):
    try:
        s, _ = req("GET", "/api/health")
        if s == 200:
            break
    except Exception:
        pass
    time.sleep(0.5)
else:
    raise SystemExit("API never became healthy")

# 0) clean stale __smoke__ projects from previous crashed runs
s, projs = req("GET", "/api/projects")
for p in projs or []:
    if p.get("name") == "__smoke__":
        s, _ = req("DELETE", f"/api/projects/{p['id']}")
        print(f"cleanup stale  : project {p['id']} -> {s}")

# 1) create project
s, proj = req("POST", "/api/projects",
              json.dumps({"name": "__smoke__", "description": "tmp"}).encode(),
              {"Content-Type": "application/json"})
print("create project :", s)
assert s == 201, f"create failed: {proj}"
pid = proj["id"]

# 2) tiny PNG upload (PIL if available, else a hardcoded 1x1 PNG)
try:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 200, 200)).save(buf, "PNG")
    png = buf.getvalue()
except ImportError:
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c4944415408d763f8ffff3f0005fe02fea735c9d40000000049454e44"
        "ae426082")

boundary = "----smoke123"
mp = (f"--{boundary}\r\n"
      "Content-Disposition: form-data; name=\"file\"; filename=\"t.png\"\r\n"
      "Content-Type: image/png\r\n\r\n").encode() + png + \
     f"\r\n--{boundary}--\r\n".encode()
s, doc = req("POST", f"/api/documents/{pid}/upload", mp,
             {"Content-Type": f"multipart/form-data; boundary={boundary}"})
print("upload doc    :", s)
assert s == 201, f"upload failed: {doc}"
did = doc["id"]

s, st = req("POST", f"/api/documents/{did}/ingest")
print("ingest doc    :", s, (st or {}).get("status"))
time.sleep(2.5)  # let the background pipeline run a bit

# 3) delete document (the endpoint that used to crash with AttributeError)
s, _ = req("DELETE", f"/api/documents/{did}")
print("delete doc    :", s)
assert s == 204, f"delete doc failed"

# 4) delete project (the other endpoint that used to crash)
s, _ = req("DELETE", f"/api/projects/{pid}")
print("delete project:", s)
assert s == 204, "delete project failed"

# 5) verify THIS run's project is gone by id
s, _ = req("GET", f"/api/projects/{pid}")
print(f"get deleted pid: {s} (expect 404)")
assert s == 404, "project row survived deletion"
print("SMOKE TEST PASSED")
