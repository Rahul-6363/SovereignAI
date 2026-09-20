"""Trust Center + audit + pages image routes."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_state
from app.models import AuditEvent, DocumentPage
from app.schemas import AuditEventOut, ModelStatusOut, TrustStatusOut
from app.services import audit

router = APIRouter(prefix="/api", tags=["trust"])


@router.get("/trust/status", response_model=TrustStatusOut)
async def trust_status():
    state = get_state()
    settings = state.settings
    gateway = state.gateway
    ollama_ok = await gateway.is_available()
    sizes = await gateway.model_sizes()
    counts = audit.counters_snapshot()

    models = [
        ModelStatusOut(
            name=settings.ollama_vision_model,
            installed=await gateway.model_installed(settings.ollama_vision_model),
            size=sizes.get(settings.ollama_vision_model, ""),
            role="Vision",
        ),
        ModelStatusOut(
            name=settings.ollama_chat_model,
            installed=await gateway.model_installed(settings.ollama_chat_model),
            size=sizes.get(settings.ollama_chat_model, ""),
            role="Chat",
        ),
        ModelStatusOut(
            name=settings.ollama_embed_model,
            installed=await gateway.model_installed(settings.ollama_embed_model),
            size=sizes.get(settings.ollama_embed_model, ""),
            role="Embedding",
        ),
    ]
    active_model = (
        settings.ollama_chat_model
        if await gateway.model_installed(settings.ollama_chat_model)
        else "deterministic-fallback"
    )
    return TrustStatusOut(
        ollama_connected=ollama_ok,
        external_llm_calls=counts.get("external_llm_calls", 0),
        network_egress="Blocked" if not settings.enable_external_network else "Allowed",
        documents_local=True,
        audit_logging=settings.enable_audit_log,
        models=models,
        active_model=active_model,
    )


@router.get("/trust/audit", response_model=list[AuditEventOut])
def audit_events(limit: int = 50, session: Session = Depends(get_session)):
    rows = session.exec(
        select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    ).all()
    return [
        AuditEventOut(
            id=r.id,
            time=r.time,
            session_id=r.session_id,
            user_action=r.user_action,
            model=r.model,
            model_version=r.model_version,
            retrieval_count=r.retrieval_count,
            tool_name=r.tool_name,
            result_status=r.result_status,
            seq=r.seq,
            entry_hash=r.entry_hash,
            prev_hash=r.prev_hash,
        )
        for r in rows
    ]


@router.get("/trust/audit/verify")
def verify_audit_chain(limit: int = 0):
    """Walk the hash chain and report the first break (README §4.11).

    This is the endpoint that turns "our audit log is tamper-evident" from a
    claim into something a judge or an auditor can press a button on.
    """
    return audit.verify_chain(limit or None)


@router.get("/trust/evidence-pack")
def evidence_pack(session: Session = Depends(get_session)):
    """Signed-shaped export of the session's provable state (README §4.10.6)."""
    state = get_state()
    settings = state.settings
    chain = audit.verify_chain()
    recent = session.exec(
        select(AuditEvent).order_by(AuditEvent.id.desc()).limit(50)
    ).all()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deployment": {
            "external_network_enabled": settings.enable_external_network,
            "audit_logging": settings.enable_audit_log,
            "model_escalation": settings.enable_model_escalation,
            "ollama_base_url": settings.ollama_base_url,
        },
        "models": {
            "chat": settings.ollama_chat_model,
            "vision": settings.ollama_vision_model,
            "embedding": settings.ollama_embed_model,
        },
        "counters": audit.counters_snapshot(),
        "audit_chain": chain,
        "recent_events": [
            {
                "seq": r.seq, "time": r.time.isoformat(), "action": r.user_action,
                "tool": r.tool_name, "model": r.model, "status": r.result_status,
                "entry_hash": r.entry_hash,
            }
            for r in reversed(recent)
        ],
    }


@router.get("/trust/metrics")
def trust_metrics():
    """Real gateway latency — the panel previously reported a hardcoded zero."""
    lat = get_state().gateway.latency
    counters = audit.counters_snapshot()
    return {
        "counters": counters,
        "latency": {
            "last_chat_ms": round(lat.last_chat_ms, 1),
            "last_embed_ms": round(lat.last_embed_ms, 1),
            "total_chat_sec": round(lat.total_chat_sec, 2),
            "chat_calls": lat.chat_calls,
            "embed_calls": lat.embed_calls,
            "avg_chat_ms": round(
                (lat.total_chat_sec * 1000 / lat.chat_calls) if lat.chat_calls else 0.0,
                1,
            ),
            "recent": lat.history[-10:],
        },
        "llm_calls": counters.get("external_llm_calls", 0),
    }


@router.get("/pages/{page_id}/image")
def page_image(page_id: int, session: Session = Depends(get_session)):
    page = session.get(DocumentPage, page_id)
    if not page or not page.image_path:
        raise HTTPException(status_code=404, detail="Page image not found")
    path = Path(page.image_path)
    if not path.is_file():
        # A row can outlive its file (manual cleanup, `make clean`): answer 404
        # instead of letting FileResponse raise a 500 from the worker.
        raise HTTPException(status_code=404, detail="Page image file is missing")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )