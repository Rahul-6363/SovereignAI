"""Plant-memory integrity check.

SQLite does not enforce foreign keys unless `PRAGMA foreign_keys=ON` is set on
every connection, so the `foreign_key=` declarations in app/models.py are
documentation, not constraints. A crashed ingest or an interrupted delete can
therefore leave rows pointing at a parent that no longer exists — they stay
invisible until they inflate a project's entity count or surface in retrieval
as evidence for a drawing nobody can open.

    python scripts/db_doctor.py          # report only
    python scripts/db_doctor.py --fix    # report, then delete the orphans
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from app.config import get_settings  # noqa: E402

# (table, column, parent table) — child rows whose parent must exist.
CHECKS = [
    ("documents", "project_id", "projects"),
    ("document_pages", "document_id", "documents"),
    ("entities", "project_id", "projects"),
    ("entities", "document_id", "documents"),
    ("entities", "page_id", "document_pages"),
    ("relationships", "project_id", "projects"),
    ("relationships", "document_id", "documents"),
    ("chunks", "project_id", "projects"),
    ("chunks", "document_id", "documents"),
    ("memories", "project_id", "projects"),
    ("conversations", "project_id", "projects"),
    ("messages", "conversation_id", "conversations"),
]


def _orphan_sql(table: str, column: str, parent: str) -> str:
    return (
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE {column} IS NOT NULL AND {column} != 0 "
        f"AND {column} NOT IN (SELECT id FROM {parent})"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fix", action="store_true", help="delete the orphaned rows")
    args = ap.parse_args()

    db_path = get_settings().database_path
    if not db_path.exists():
        print(f"No database at {db_path} — nothing to check.")
        return 0

    conn = sqlite3.connect(db_path)
    tables = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    total = 0
    print(f"Checking {db_path}\n")
    for table, column, parent in CHECKS:
        if table not in tables or parent not in tables:
            continue
        (count,) = conn.execute(_orphan_sql(table, column, parent)).fetchone()
        if count == 0:
            print(f"  ok      {table}.{column} -> {parent}")
            continue
        total += count
        print(f"  ORPHAN  {table}.{column} -> {parent}: {count} row(s)")
        if args.fix:
            conn.execute(
                f"DELETE FROM {table} WHERE {column} IS NOT NULL AND {column} != 0 "
                f"AND {column} NOT IN (SELECT id FROM {parent})"
            )

    if args.fix and total:
        conn.commit()
        conn.execute("VACUUM")
        print(f"\nDeleted {total} orphaned row(s).")
    elif total:
        print(f"\n{total} orphaned row(s). Re-run with --fix to delete them.")
    else:
        print("\nNo orphans found.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
