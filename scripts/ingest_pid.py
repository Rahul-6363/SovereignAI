"""CLI helper to upload + ingest a P&ID through the API routes.

Usage:
    python scripts/ingest_pid.py --file data/demo/pid/unit-a-pid.png --project "Demo Plant"

Requires the API to be running on http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload and ingest a P&ID")
    parser.add_argument("--file", required=True, help="path to the P&ID file")
    parser.add_argument("--project", default=None, help="project name (created if missing)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"file not found: {path}")
        return 1

    with httpx.Client(timeout=30) as client:
        # find or create project
        projects = client.get(f"{API}/api/projects").json()
        project = next(
            (p for p in projects if p["name"].lower() == (args.project or "").lower()),
            None,
        )
        if not project:
            resp = client.post(f"{API}/api/projects", json={"name": args.project or "CLI Import"})
            project = resp.json()
        pid = project["id"]

        with open(path, "rb") as fh:
            resp = client.post(
                f"{API}/api/documents/{pid}/upload",
                files={"file": (path.name, fh, "application/octet-stream")},
            )
            resp.raise_for_status()
        doc = resp.json()
        print(f"uploaded document id={doc['id']} name={doc['name']}")

        resp = client.post(f"{API}/api/documents/{doc['id']}/ingest")
        print("ingestion started:", resp.json())

        # poll
        for _ in range(240):
            time.sleep(0.5)
            status = client.get(f"{API}/api/documents/{doc['id']}/status").json()
            print(
                f"\rstatus: {status['status']} · stage: {status['stage']} · "
                f"entities: {status['entities']} · relations: {status['relationships']}",
                end="",
                flush=True,
            )
            if status["status"] in ("ready", "failed"):
                print()
                if status["status"] == "failed":
                    print("error:", status["error"])
                    return 1
                return 0
        print("\ntimed out waiting for ingestion")
        return 1


if __name__ == "__main__":
    sys.exit(main())