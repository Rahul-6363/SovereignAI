"""Chat routes — conversations + SSE grounded chat stream."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.db import engine, get_session
from app.deps import get_state
from app.models import Conversation, Message, Project
from app.schemas import (
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    ConversationRename,
    MessageOut,
)
from app.services import audit

router = APIRouter(prefix="/api", tags=["chat"])


def _event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/projects/{project_id}/chat")
async def chat_stream(
    project_id: int,
    body: ChatRequest,
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    state = get_state()

    # ── resolve / create conversation ────────────────────────
    conv = None
    if body.conversation_id:
        conv = session.get(Conversation, body.conversation_id)
    if conv is None or conv.project_id != project_id:
        conv = Conversation(
            project_id=project_id,
            title=(body.message[:48] or "New chat"),
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)
    else:
        from app.db import utcnow

        conv.updated_at = utcnow()
        # A thread opened empty from the rail is titled "New chat"; the first
        # real question is the only good name anyone would give it.
        if conv.title.strip().lower() in ("", "new chat"):
            conv.title = body.message.strip()[:48] or conv.title
        session.add(conv)
        session.commit()
        session.refresh(conv)

    # Plain int, read before the generator starts: the request session may be
    # closed by the time SSE events are produced, and touching an ORM
    # attribute then raises DetachedInstanceError in the middle of the
    # stream — which the client sees as a response that just stops.
    conversation_id = int(conv.id)

    # persist user message
    user_msg = Message(
        conversation_id=conversation_id, role="user", content=body.message
    )
    session.add(user_msg)
    session.commit()
    session.refresh(user_msg)

    # Prior turns of this conversation, excluding the message just persisted —
    # the generator uses them so follow-ups ("and its upstream?") resolve.
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.id < user_msg.id)
        .order_by(Message.id.desc())
        .limit(12)
    ).all()
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(rows)
        if m.role in ("user", "assistant") and m.content.strip()
    ]

    session_id = str(uuid.uuid4())[:8]

    async def gen():
        yield _event("status", {"stage": "session", "conversation_id": conversation_id})
        try:
            # The shared graph is rebuilt on ingest, but an API restart leaves
            # it empty — rebuild per request so evidence always has graph
            # context (cheap: reads entities/relationships from SQLite).
            state.graph.rebuild(session, project_id)
            message_parts: list[str] = []
            confidence = 0.0
            claims = []
            sources = []
            intent = ""
            model = ""
            async for ev in state.answer_generator.stream_chat(
                session=session,
                project_id=project_id,
                question=body.message,
                top_k=body.retrieval_top_k,
                session_id=session_id,
                history=history,
            ):
                etype = ev["type"]
                yield _event(etype, ev)
                if etype == "token":
                    message_parts.append(ev["text"])
                elif etype == "done":
                    confidence = ev.get("confidence", 0.0)
                    claims = ev.get("claims", [])
                    sources = ev.get("sources", [])
                    intent = ev.get("intent", "")
                    model = ev.get("model", "")
            # persist assistant message
            full = "".join(message_parts)
            assistant = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=full,
                confidence=confidence,
                claims_json=json.dumps(claims, ensure_ascii=False),
                sources_json=json.dumps(sources, ensure_ascii=False),
                kind="chat",
            )
            with Session(engine) as s2:
                s2.add(assistant)
                s2.commit()
                s2.refresh(assistant)
            yield _event(
                "done_meta",
                {
                    "message_id": assistant.id,
                    "conversation_id": conversation_id,
                    "intent": intent,
                    "model": model,
                    "confidence": confidence,
                },
            )
        except Exception as exc:
            audit.record_event(user_action="chat", result_status="failed", session_id=session_id)
            yield _event("error", {"message": str(exc)[:300]})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _conversation_out(session: Session, conv: Conversation) -> ConversationOut:
    """One rail row, including the counts the sidebar renders.

    The preview is the FIRST user turn, not the newest message: a chat rail is
    scanned to find a past thread again, and the question you asked is what
    you remember it by.
    """
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.id)
    ).all()
    first_user = next((m for m in rows if m.role == "user"), None)
    return ConversationOut(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title or "New chat",
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(rows),
        preview=(first_user.content[:120] if first_user else ""),
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(session: Session = Depends(get_session)):
    rows = session.exec(
        select(Conversation).order_by(Conversation.updated_at.desc()).limit(100)
    ).all()
    return [_conversation_out(session, c) for c in rows]


@router.get(
    "/projects/{project_id}/conversations", response_model=list[ConversationOut]
)
def project_conversations(
    project_id: int, session: Session = Depends(get_session)
):
    """Every chat thread in one project, newest activity first."""
    if not session.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    rows = session.exec(
        select(Conversation)
        .where(Conversation.project_id == project_id)
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    ).all()
    return [_conversation_out(session, c) for c in rows]


@router.post(
    "/projects/{project_id}/conversations",
    response_model=ConversationOut,
    status_code=201,
)
def create_conversation(
    project_id: int,
    body: ConversationCreate | None = None,
    session: Session = Depends(get_session),
):
    """Start an empty thread.

    Explicit creation, rather than letting the first message implicitly make
    one, is what lets the UI open a blank chat and still have somewhere to put
    an uploaded file or a title before anything is asked.
    """
    if not session.get(Project, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    conv = Conversation(
        project_id=project_id,
        title=(body.title if body and body.title else "New chat"),
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return _conversation_out(session, conv)


@router.patch(
    "/conversations/{conversation_id}", response_model=ConversationOut
)
def rename_conversation(
    conversation_id: int,
    body: ConversationRename,
    session: Session = Depends(get_session),
):
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.title = body.title.strip()[:120] or conv.title
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return _conversation_out(session, conv)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int, session: Session = Depends(get_session)
):
    """Remove a thread and its messages.

    Messages go first: SQLite does not enforce the foreign key, so deleting
    only the parent would leave orphaned rows that nothing ever lists again.
    """
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    session.execute(
        sa_delete(Message).where(Message.conversation_id == conversation_id)
    )
    session.delete(conv)
    session.commit()


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, session: Session = Depends(get_session)):
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _conversation_out(session, conv)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def conversation_messages(
    conversation_id: int, session: Session = Depends(get_session)
):
    """Full transcript, with the evidence and artefacts each turn produced.

    Returning these alongside the text is what makes a reopened conversation
    identical to the live one — citations still resolve and generated files
    are still downloadable, instead of the thread degrading to plain text.
    """
    conv = session.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id)
    ).all()

    def _json(raw: str, default):
        try:
            value = json.loads(raw or "")
        except ValueError:
            return default
        return value if isinstance(value, list) else default

    return [
        MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            confidence=m.confidence,
            created_at=m.created_at,
            kind=getattr(m, "kind", "chat") or "chat",
            sources=_json(m.sources_json, []),
            claims=_json(m.claims_json, []),
            artifacts=_json(getattr(m, "artifacts_json", "[]"), []),
        )
        for m in rows
    ]
