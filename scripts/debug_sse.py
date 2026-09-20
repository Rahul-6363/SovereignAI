"""Debug the SSE stream from chat endpoint."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as client:
    pid = 1
    r = client.post(
        f"/api/projects/{pid}/chat",
        json={"message": "Which instruments are associated with P-101?"},
    )
    print("status:", r.status_code)
    print("content-type:", r.headers.get("content-type"))
    body = r.text
    print("length:", len(body))
    print("---- first 3000 chars ----")
    print(body[:3000])
    print("---- last 1500 chars ----")
    print(body[-1500:])