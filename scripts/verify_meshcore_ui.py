"""Meshcore main-UI journey verification (README §0.1 / §7 Phase 0).

Boots nothing itself — point it at a running API (default :8000) and a running
web server (default :3000) and it asserts:

  1. the shared session context exists  (project -> conversations -> messages)
  2. the main workspace renders the Claude-like front door
  3. clicking P&ID deep-links into the *existing* P&ID interface
  4. the return path back to the workspace exists
  5. the product-status boundary is stated on screen

Usage:
    python scripts/verify_meshcore_ui.py [--api http://127.0.0.1:8000]
                                         [--web http://127.0.0.1:3000]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PASS, FAIL = "PASS", "FAIL"
_failures = 0


def check(label: str, cond: bool, extra: str = "") -> None:
    global _failures
    print(f"{PASS if cond else FAIL}  {label}" + (f"  ({extra})" if extra else ""))
    if not cond:
        _failures += 1


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_text(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # 404 etc. are still renderable pages
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--web", default="http://127.0.0.1:3000")
    args = ap.parse_args()
    api, web = args.api.rstrip("/"), args.web.rstrip("/")

    # ── shared session/project context ───────────────────────────────
    try:
        projects = get_json(f"{api}/api/projects")
        check("GET /api/projects", isinstance(projects, list), f"n={len(projects)}")
    except Exception as e:  # pragma: no cover - environment dependent
        check("GET /api/projects", False, str(e))
        print("\nIs the API running?  cd apps/api && python -m uvicorn app.main:app")
        return 1
    if not projects:
        print("NOTE  no projects exist yet — create one to exercise project pages")
        return _failures

    pid = projects[0]["id"]

    convs = get_json(f"{api}/api/projects/{pid}/conversations")
    check(
        "GET /api/projects/{id}/conversations (shared session context)",
        isinstance(convs, list),
        f"n={len(convs)}",
    )

    if convs:
        cid = convs[0]["id"]
        one = get_json(f"{api}/api/conversations/{cid}")
        check(
            "GET /api/conversations/{id}",
            one.get("project_id") == pid,
            f"title={one.get('title','')[:40]!r}",
        )
        msgs = get_json(f"{api}/api/conversations/{cid}/messages")
        check(
            "GET /api/conversations/{id}/messages (history restorable)",
            isinstance(msgs, list),
            f"n={len(msgs)}",
        )

    # ── main workspace ───────────────────────────────────────────────
    status, html = get_text(f"{web}/")
    check("main workspace (/) -> 200", status == 200, f"got {status}")
    check("branded as Meshcore (single product name)", "Meshcore" in html)
    check(
        "capability launcher present",
        "Capabilities" in html and "first-class" in html,
    )
    check(
        "Claude-like composer present",
        "Start task" in html and "Describe the task" in html,
    )
    check("live egress counter present", "egress" in html)
    check(
        "explicit product-status boundary",
        "Completed" in html and "Starting now" in html and "Next" in html,
    )

    # ── P&ID entry point (must open the EXISTING interface) ──────────
    status, html = get_text(f"{web}/projects/{pid}?view=pid&from=meshcore")
    check("?view=pid -> 200", status == 200, f"got {status}")
    check(
        "P&ID view states it is the completed module",
        "completed module" in html,
    )
    check(
        "P&ID view reuses the existing upload/explorer interface",
        "Upload" in html and "Entities" in html,
    )
    check("return path into agent chat present", "Continue in agent chat" in html)

    # ── return path back to the main workspace ───────────────────────
    check("link back to Meshcore home", "Meshcore home" in html or "← Meshcore" in html)

    # ── capability views ─────────────────────────────────────────────
    status, html = get_text(f"{web}/projects/{pid}?view=overview")
    check("?view=overview -> 200", status == 200, f"got {status}")
    check("overview exposes capabilities", "Capabilities" in html)
    check("overview states project status", "Project status" in html)

    status, html = get_text(f"{web}/projects/{pid}?view=deliverables")
    check("?view=deliverables -> 200", status == 200, f"got {status}")
    check(
        "deliverables view states its roadmap phase honestly",
        "Deliverables" in html and "Product status" in html,
    )

    status, html = get_text(f"{web}/projects/{pid}?view=chat&q=test")
    check("?view=chat&q= (home-composer handoff) -> 200", status == 200, f"got {status}")
    check("chat view present", "Ask" in html)

    status, html = get_text(f"{web}/workspace")
    check("projects management page -> 200", status == 200, f"got {status}")
    check("projects page has create form", "Create" in html and "name=" in html)

    print()
    if _failures:
        print(f"{_failures} check(s) failed")
    else:
        print("all Meshcore main-UI journey checks passed")
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())