"""Audit logging — every model / tool / retrieval event is recorded.

The log is hash-chained (README §4.11): each entry carries the hash of the
one before it, so the sequence cannot be edited after the fact without the
break being detectable. `verify_chain` is what turns that from a claim into
something an auditor can check.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import engine
from app.models import AuditEvent

_settings = get_settings()

# In-memory counters surfaced by the Trust Center (does not require polling).
_metrics_lock = threading.Lock()
_counters = {
    "external_llm_calls": 0,
    "tools_invoked": 0,
    "chats": 0,
    "retrievals": 0,
    "extractions": 0,
}


def bump(counter: str, amount: int = 1) -> None:
    with _metrics_lock:
        _counters[counter] = _counters.get(counter, 0) + amount


def counters_snapshot() -> dict:
    with _metrics_lock:
        return dict(_counters)


# Appends must serialise, or two concurrent writers both read the same head
# and produce a fork in the chain.
_chain_lock = threading.Lock()

GENESIS_HASH = "0" * 64


def canonical_json(entry: dict) -> str:
    """Stable serialisation — the hash must not depend on key order."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(entry: dict) -> str:
    return hashlib.sha256(canonical_json(entry).encode("utf-8")).hexdigest()


def _canonical_time(value) -> str:
    """Timestamp in a form that survives a round-trip through SQLite.

    SQLite has no native datetime, so the tz-aware value written here comes
    back naive. Hashing `isoformat()` directly would therefore make every
    entry appear altered the moment it is read back. Normalising to naive
    UTC microseconds hashes the same before and after storage.
    """
    if value is None:
        return ""
    if getattr(value, "tzinfo", None) is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _chain_payload(event: AuditEvent) -> dict:
    """The fields covered by the hash. Anything omitted here is not protected."""
    return {
        "seq": event.seq,
        "time": _canonical_time(event.time),
        "session_id": event.session_id,
        "user_action": event.user_action,
        "model": event.model,
        "model_version": event.model_version,
        "retrieval_count": event.retrieval_count,
        "tool_name": event.tool_name,
        "result_status": event.result_status,
        "prev_hash": event.prev_hash,
    }


def _record(
    session_id: str,
    user_action: str,
    model: str = "",
    model_version: str = "",
    retrieval_count: int = 0,
    tool_name: str = "",
    result_status: str = "ok",
) -> None:
    if not _settings.enable_audit_log:
        return
    try:
        with _chain_lock, Session(engine) as session:
            # The head is the last CHAINED entry. Entries written before the
            # chain existed have seq 0 and no hash; anchoring to one would
            # start the chain with an empty prev_hash and fail verification.
            head = session.exec(
                select(AuditEvent)
                .where(AuditEvent.entry_hash != "")
                .order_by(AuditEvent.seq.desc())
                .limit(1)
            ).first()
            event = AuditEvent(
                time=datetime.now(timezone.utc),
                session_id=session_id[:64],
                user_action=user_action[:128],
                model=model[:64],
                model_version=model_version[:32],
                retrieval_count=int(retrieval_count or 0),
                tool_name=tool_name[:64],
                result_status=result_status[:16],
                seq=(head.seq + 1) if head else 1,
                prev_hash=head.entry_hash if head else GENESIS_HASH,
            )
            event.entry_hash = compute_hash(_chain_payload(event))
            session.add(event)
            session.commit()
    except Exception:
        # Audit must never break the application.
        pass


def verify_chain(limit: Optional[int] = None) -> dict:
    """Walk the chain and report the first break, if any.

    An auditor's question is "has this log been edited?", and the answer has
    to be checkable without trusting the process that wrote it.
    """
    try:
        with Session(engine) as session:
            stmt = select(AuditEvent).order_by(AuditEvent.seq)
            rows = session.exec(stmt).all()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "checked": 0}

    # Entries written before the chain existed carry no hash. They are
    # reported as unchained rather than as tampering — claiming a break where
    # there is only history would make the check useless.
    legacy = [e for e in rows if not e.entry_hash or e.seq <= 0]
    rows = [e for e in rows if e.entry_hash and e.seq > 0]

    if limit:
        rows = rows[-limit:]
    if not rows:
        return {
            "ok": True, "checked": 0, "head": None,
            "unchained_legacy_entries": len(legacy),
            "message": "no chained entries yet",
        }

    expected_prev = GENESIS_HASH if rows[0].seq == 1 else rows[0].prev_hash
    broken_at = None
    for event in rows:
        if event.prev_hash != expected_prev:
            broken_at = {"seq": event.seq, "reason": "prev_hash mismatch"}
            break
        recomputed = compute_hash(_chain_payload(event))
        if recomputed != event.entry_hash:
            broken_at = {"seq": event.seq, "reason": "entry content altered"}
            break
        expected_prev = event.entry_hash

    return {
        "ok": broken_at is None,
        "checked": len(rows),
        "head": rows[-1].entry_hash,
        "head_seq": rows[-1].seq,
        "broken_at": broken_at,
        "unchained_legacy_entries": len(legacy),
    }


def record_event(
    user_action: str,
    model: str = "",
    session_id: str = "cli",
    retrieval_count: int = 0,
    tool_name: str = "",
    result_status: str = "ok",
) -> None:
    _record(session_id, user_action, model, "", retrieval_count, tool_name, result_status)
    if user_action == "chat":
        bump("chats")
    if retrieval_count:
        bump("retrievals", retrieval_count)
    if tool_name:
        bump("tools_invoked")


def recent_events(limit: int = 50) -> list[dict]:
    try:
        with Session(engine) as session:
            rows = session.exec(
                select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
            ).all()
            return [json.loads(r.model_dump_json() if hasattr(r, "model_dump_json") else "{}") for r in rows]
    except Exception:
        return []