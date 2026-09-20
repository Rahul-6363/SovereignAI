"""Agent task + deliverable routes (README Phase 1).

Exposes the bounded agent loop as an SSE stream so the workspace can show the
plan, each policy decision and each typed tool call as they happen — the
"tool/activity trace" the main UI is specified around — and serves the
rendered artefacts for download.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.deps import get_state
from app.db import engine
from app.models import Conversation, Message, Project
from app.services import agent as agent_service
from app.services import tools as tool_registry

router = APIRouter(prefix="/api", tags=["deliverables"])
settings = get_settings()


def _event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _project_dir(project_id: int) -> Path:
    out = settings.deliverable_path / f"project-{project_id}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _artifact_payload(project_id: int, path: Path) -> dict:
    """Shape one file as the UI's DeliverableRec."""
    stat = path.stat()
    return {
        "id": f"{project_id}:{path.name}",
        "name": path.name,
        "kind": path.suffix.lstrip(".").lower() or "other",
        "url": f"/api/projects/{project_id}/deliverables/{path.name}",
        "created_at": __import__("datetime").datetime.fromtimestamp(
            stat.st_mtime, __import__("datetime").timezone.utc
        ).isoformat(),
        "size_bytes": stat.st_size,
    }


def _resolve_conversation(
    session: Session, project_id: int, raw_id, prompt: str
) -> Conversation:
    """Find the thread this task belongs to, or open one named after it."""
    conv = None
    if raw_id:
        try:
            conv = session.get(Conversation, int(raw_id))
        except (TypeError, ValueError):
            conv = None
    if conv is None or conv.project_id != project_id:
        conv = Conversation(project_id=project_id, title=prompt[:48] or "New chat")
        session.add(conv)
        session.commit()
        session.refresh(conv)
        return conv

    from app.db import utcnow

    conv.updated_at = utcnow()
    if conv.title.strip().lower() in ("", "new chat"):
        conv.title = prompt.strip()[:48] or conv.title
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


def _history(session: Session, conversation_id: int, before_id: int) -> list[dict]:
    """Prior turns, so an agent task can resolve "put that in a spreadsheet"."""
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.id < before_id)
        .order_by(Message.id.desc())
        .limit(12)
    ).all()
    return [
        {"role": m.role, "content": m.content}
        for m in reversed(rows)
        if m.role in ("user", "assistant") and m.content.strip()
    ]


def _persist_agent_turn(conversation_id: int, text: str, artifacts: list[dict]) -> None:
    """Write the agent's reply on its own session.

    The request session is already committed to the SSE response by this
    point, so the turn is saved through a fresh one — the same reason the
    chat stream does.
    """
    with Session(engine) as s2:
        s2.add(
            Message(
                conversation_id=conversation_id,
                role="assistant",
                content=text.strip(),
                kind="agent",
                artifacts_json=json.dumps(artifacts, ensure_ascii=False),
            )
        )
        s2.commit()


@router.get("/tools")
def list_tools():
    """The typed tool registry — the agent's entire action space."""
    from app.services.calc_engine import list_operations

    return {
        "tools": tool_registry.describe_tools(),
        "calculations": list_operations(),
        "budgets": {
            "max_replans": agent_service.MAX_REPLANS,
            "max_tool_calls": agent_service.MAX_TOOL_CALLS,
            "wall_clock_seconds": agent_service.WALL_CLOCK_SECONDS,
        },
    }


@router.post("/projects/{project_id}/agent")
async def run_agent_task(
    project_id: int,
    body: dict,
    session: Session = Depends(get_session),
):
    """Run one bounded agent task, streaming plan → policy → tools → deliver."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    prompt = str(body.get("prompt") or body.get("message") or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    clearance = str(body.get("clearance") or "internal")

    # An agent turn belongs to the same thread as the chat turns around it.
    # Without this the conversation reads as if the user asked for a document
    # and nothing answered — and the file it produced is lost on reload.
    conv = _resolve_conversation(session, project_id, body.get("conversation_id"), prompt)
    # Read the ids out as plain ints NOW. The request session is closed by the
    # time the SSE generator runs, and touching an ORM attribute after that
    # raises DetachedInstanceError mid-stream — which surfaces as a response
    # that simply stops, with no error event.
    conversation_id = int(conv.id)
    user_msg = Message(
        conversation_id=conversation_id, role="user", content=prompt, kind="agent"
    )
    session.add(user_msg)
    session.commit()
    user_msg_id = int(user_msg.id)
    history = _history(session, conversation_id, user_msg_id)

    state = get_state()
    out_dir = _project_dir(project_id)
    session_id = str(uuid.uuid4())[:8]

    async def gen():
        yield _event("status", {"stage": "session", "conversation_id": conversation_id})
        answer_parts: list[str] = []
        artifacts: list[dict] = []
        try:
            async for ev in agent_service.run_agent(
                session=session,
                state=state,
                project_id=project_id,
                prompt=prompt,
                out_dir=out_dir,
                clearance=clearance,
                session_id=session_id,
                history=history,
            ):
                if ev.get("type") == "agent_done":
                    ev["artifacts"] = [
                        _artifact_payload(project_id, Path(a["path"]))
                        | {"citations": a.get("citations", 0)}
                        for a in ev.get("artifacts", [])
                        if Path(a["path"]).exists()
                    ]
                    artifacts = ev["artifacts"]
                    answer_parts.append(str(ev.get("message") or ev.get("summary") or ""))
                elif ev.get("type") == "token":
                    answer_parts.append(str(ev.get("text") or ""))
                ev["conversation_id"] = conversation_id
                yield _event(ev.get("type", "message"), ev)

            _persist_agent_turn(conversation_id, "".join(answer_parts), artifacts)
            yield _event(
                "done_meta",
                {"conversation_id": conversation_id, "artifacts": artifacts},
            )
        except Exception as exc:
            _persist_agent_turn(
                conversation_id,
                "".join(answer_parts) or f"Task failed: {exc}",
                artifacts,
            )
            yield _event("error", {"message": str(exc)[:300]})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/projects/{project_id}/deliverables")
def list_deliverables(project_id: int, session: Session = Depends(get_session)):
    """Everything this project has produced, newest first."""
    if not session.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    out = _project_dir(project_id)
    files = [
        p for p in out.iterdir()
        if p.is_file() and not p.name.endswith(".provenance.json")
    ]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    payload = []
    for f in files:
        item = _artifact_payload(project_id, f)
        prov = out / f"{f.stem}.provenance.json"
        if prov.exists():
            try:
                item["citations"] = len(
                    json.loads(prov.read_text(encoding="utf-8")).get("citations", [])
                )
            except ValueError:
                item["citations"] = 0
        payload.append(item)
    return payload


@router.get("/projects/{project_id}/deliverables/{filename}")
def download_deliverable(project_id: int, filename: str):
    """Serve one rendered artefact."""
    # Reject traversal outright rather than sanitising: the only legitimate
    # value here is a bare filename this API itself produced.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = _project_dir(project_id) / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/octet-stream",
    )


@router.get("/projects/{project_id}/deliverables/{filename}/provenance")
def deliverable_provenance(project_id: int, filename: str):
    """The evidence sidecar for one artefact."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    stem = Path(filename).stem
    path = _project_dir(project_id) / f"{stem}.provenance.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No provenance recorded")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("/calculate")
def run_calculation(body: dict):
    """Direct access to the deterministic engine, with no model in the path."""
    from app.services.calc_engine import CalculationError, calculate

    try:
        result = calculate(
            str(body.get("operation", "")),
            body.get("inputs") or {},
            body.get("output_unit") or None,
        )
    except CalculationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result.as_dict()
