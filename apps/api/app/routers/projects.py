"""Project routes - CRUD + stats + memory graph + delete."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_state
from app.models import (
    Chunk,
    Conversation,
    Document,
    DocumentPage,
    Entity,
    Memory,
    Message,
    Project,
    Relationship,
)
from app.schemas import (
    MemoryGraphOut,
    ProjectCreate,
    ProjectOut,
    ProjectStats,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.services.evidence_builder import attach_document_meta, build_evidence_packet
from app.services.query_router import classify
from app.services.graph_memory import to_graph_payload

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _stats(session: Session, project_id: int) -> ProjectStats:
    docs = session.exec(select(Document).where(Document.project_id == project_id)).all()
    ents = session.exec(select(Entity).where(Entity.project_id == project_id)).all()
    rels = session.exec(select(Relationship).where(Relationship.project_id == project_id)).all()
    mems = session.exec(select(Memory).where(Memory.project_id == project_id)).all()
    chunks = session.exec(select(Chunk).where(Chunk.project_id == project_id)).all()
    ready_docs = [d for d in docs if d.status == "ready"]
    last_indexed = max((d.created_at for d in ready_docs), default=None)
    return ProjectStats(
        documents=len(docs),
        entities=len(ents),
        relationships=len(rels),
        memories=len(mems),
        chunks=len(chunks),
        last_indexed_at=last_indexed,
    )


def _to_out(session: Session, p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        description=p.description,
        created_at=p.created_at,
        stats=_stats(session, p.id),
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)):
    projects = session.exec(select(Project).order_by(Project.id.desc())).all()
    return [_to_out(session, p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectCreate, session: Session = Depends(get_session),
):
    project = Project(name=body.name.strip(), description=body.description)
    session.add(project)
    session.commit()
    session.refresh(project)
    return _to_out(session, project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_out(session, project)


def _unlink_quietly(path: str) -> None:
    """Best-effort file removal; never blocks the API response."""
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
    except OSError:
        pass


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)):
    """Cascade-delete a project and all child rows, then best-effort clean files."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Collect file paths BEFORE rows are gone so nothing leaks on disk.
    docs = session.exec(select(Document).where(Document.project_id == project_id)).all()
    doc_ids = [d.id for d in docs if d.id is not None]
    doc_paths = [d.path for d in docs if d.path]
    page_image_paths: list[str] = []
    if doc_ids:
        pages = session.exec(
            select(DocumentPage).where(DocumentPage.document_id.in_(doc_ids))
        ).all()
        page_image_paths = [p.image_path for p in pages if p.image_path]

    # Children first, parents last (FK-safe bulk deletes).
    session.execute(sa_delete(Message).where(
        Message.conversation_id.in_(
            select(Conversation.id).where(Conversation.project_id == project_id)
        )
    ))
    session.execute(sa_delete(Conversation).where(
        Conversation.project_id == project_id
    ))
    session.execute(sa_delete(Memory).where(Memory.project_id == project_id))
    session.execute(sa_delete(Entity).where(Entity.project_id == project_id))
    session.execute(sa_delete(Relationship).where(
        Relationship.project_id == project_id
    ))
    session.execute(sa_delete(Chunk).where(Chunk.project_id == project_id))
    if doc_ids:
        session.execute(sa_delete(DocumentPage).where(
            DocumentPage.document_id.in_(doc_ids)
        ))
    session.execute(sa_delete(Document).where(Document.project_id == project_id))
    session.delete(project)
    session.commit()

    for path in [*doc_paths, *page_image_paths]:
        _unlink_quietly(path)


@router.get("/{project_id}/memory/graph", response_model=MemoryGraphOut)
def project_graph(project_id: int, session: Session = Depends(get_session)):
    state = get_state()
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    graph = state.graph.rebuild(session, project_id)
    return MemoryGraphOut(**to_graph_payload(graph, project_id))


@router.post("/{project_id}/search", response_model=SearchResponse)
async def project_search(
    project_id: int,
    body: SearchRequest,
    session: Session = Depends(get_session),
):
    """Hybrid retrieval with the same evidence packet the chat pipeline uses."""
    state = get_state()
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # The in-memory graph is per-process and empty after a restart; without
    # this the graph leg of hybrid retrieval silently contributes nothing.
    state.graph.rebuild(session, project_id)

    results = await state.retriever.retrieve(
        session, project_id, body.query, top_k=body.top_k
    )
    intent = classify(body.query)["intent"]
    packet = build_evidence_packet(
        session, project_id, body.query, state.graph, results
    )
    packet["query_intent"] = intent
    packet = attach_document_meta(session, packet)

    items = [
        SearchResultItem(
            rank=r.get("rank", i + 1),
            source_type=str(r.get("source", "chunk")),
            tag=r.get("tag"),
            text=r.get("text"),
            page=r.get("page_id"),
            bbox=r.get("bbox"),
            score=float(r.get("score", 0.0) or 0.0),
            confidence=float(r.get("confidence", 0.0) or 0.0),
        )
        for i, r in enumerate(results[: body.top_k])
    ]
    return SearchResponse(
        query=body.query, intent=intent, results=items, evidence=packet
    )
