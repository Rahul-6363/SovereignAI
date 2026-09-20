"""Test isolation.

The suite used to run against the real development database
(`data/plant_memory.db`): it ingested a demo P&ID, then tore down only the
`documents` and `projects` rows, leaving every entity, relationship, chunk,
page and memory behind. Those orphans inflated real project statistics, and
because SQLite reuses rowids, a newly created project could inherit the
extracted entities of a long-deleted one.

Pointing DATABASE_URL at a throwaway file before the app is imported keeps
test data out of the developer's workspace entirely. Environment variables
take precedence over the repo `.env`, so this wins without editing config.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP_DB = Path(tempfile.gettempdir()) / "meshcore-tests" / "plant_memory.db"
_TMP_DB.parent.mkdir(parents=True, exist_ok=True)

# Must happen before `app.config` is imported anywhere in the test session.
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

# A fresh file per session: no state carried between runs.
for suffix in ("", "-wal", "-shm"):
    stale = Path(str(_TMP_DB) + suffix)
    if stale.exists():
        stale.unlink()
