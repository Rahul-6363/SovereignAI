"""Document routes — upload, ingest, status, entities, pages."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_session
from app.deps import get_state
from app.models import (
    Chunk,
    Document,
    DocumentPage,
    Entity,
    Memory,
    Project,
    Relationship,
)
from app.schemas import (
    DocumentOut,
    EntityDetailOut,
    EntityOut,
    IngestionStatusOut,
    PageOut,
    RelationshipOut,
)
from app.services.pid_parser import hash_bytes, normalize_mime, safe_filename

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()


def _unlink_quietly(path: str) -> None:
    """Best-effort file removal; never blocks the API response."""
    try:
        p = Path(path)
        if p.exists():
            p.unlink()
    except OSError:
        pass


def _doc_out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=d.id,
        project_id=d.project_id,
        name=d.name,
        mime_type=d.mime_type,
        sha256=d.sha256,
        status=d.status,
        stage=d.stage,
        page_count=d.page_count,
        error=d.error,
        created_at=d.created_at,
    )


@router.post("/{project_id}/upload", response_model=DocumentOut, status_code=201)
async def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")
    mime = normalize_mime(file.filename or "upload.bin", content)
    if "pdf" not in mime and not mime.startswith("image/"):
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {mime}")

    # Two uploads named "pid.pdf" must not overwrite each other — the content
    # hash makes the stored name unique while staying human-recognisable.
    digest = hash_bytes(content)
    stem = safe_filename(Path(file.filename or "upload").stem)
    suffix = safe_filename(Path(file.filename or "upload").suffix) or ".bin"
    upload_path = settings.upload_path / f"{stem}-{digest[:12]}{suffix}"
    upload_path.write_bytes(content)

    doc = Document(
        project_id=project_id,
        name=(file.filename or "upload").strip(),
        mime_type=mime,
        path=str(upload_path),
        sha256=hash_bytes(content),
        status="uploaded",
        stage="uploaded",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return _doc_out(doc)


@router.post("/{document_id}/ingest", response_model=IngestionStatusOut)
async def ingest_document(
    document_id: int,
    session: Session = Depends(get_session),
):
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    state = get_state()
    if doc.status == "processing" and doc.id not in state.pipeline.active:
        # A previous run died mid-flight (e.g. server restart while the vision
        # model was busy) — recover instead of polling "processing" forever.
        doc.status = "uploaded"
        doc.stage = "queued"
        doc.error = "previous ingestion was interrupted; retrying"
        session.add(doc)
        session.commit()
    elif doc.status == "processing":
        return _status_out(session, doc, progress=0.3)

    doc.status = "processing"
    doc.stage = "queued"
    doc.error = ""
    session.add(doc)
    session.commit()
    state.graph.rebuild(session, doc.project_id)

    # Off the event loop entirely — see IngestionPipeline.spawn. Running this
    # as a background *task* is what made the UI look hung: the poll it needs
    # to report progress could not be served while the page was extracting.
    state.pipeline.spawn(document_id)
    return _status_out(session, doc, progress=0.05)


@router.get("/{document_id}/status", response_model=IngestionStatusOut)
def document_status(document_id: int, session: Session = Depends(get_session)):
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _status_out(session, doc)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, session: Session = Depends(get_session)):
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return _doc_out(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    project_id: int | None = None, session: Session = Depends(get_session)
):
    """All documents, or just one project's when `project_id` is given.

    The workspace file rail is project-scoped: without the filter it listed
    every project's drawings in every project.
    """
    stmt = select(Document).order_by(Document.id.desc())
    if project_id is not None:
        stmt = stmt.where(Document.project_id == project_id)
    return [_doc_out(d) for d in session.exec(stmt).all()]


@router.get("/{document_id}/pages", response_model=list[PageOut])
def document_pages(document_id: int, session: Session = Depends(get_session)):
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    pages = session.exec(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    ).all()
    return [
        PageOut(
            id=p.id,
            document_id=p.document_id,
            page_number=p.page_number,
            image_url=f"/api/pages/{p.id}/image",
            width=p.width,
            height=p.height,
        )
        for p in pages
    ]


@router.get("/{document_id}/entities", response_model=list[EntityOut])
def document_entities(document_id: int, session: Session = Depends(get_session)):
    rows = session.exec(
        select(Entity).where(Entity.document_id == document_id).order_by(Entity.id)
    ).all()
    return [_entity_out(e) for e in rows]


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, session: Session = Depends(get_session)):
    """Cascade-delete one document: pages, entities, links, chunks + files."""
    doc = session.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    project_id = doc.project_id
    doc_path = doc.path  # capture now: the instance expires after commit

    # Collect file paths BEFORE rows are gone so nothing leaks on disk.
    pages = session.exec(
        select(DocumentPage).where(DocumentPage.document_id == document_id)
    ).all()
    page_image_paths = [p.image_path for p in pages if p.image_path]

    # Children first, parent last (FK-safe bulk deletes).
    session.execute(sa_delete(DocumentPage).where(
        DocumentPage.document_id == document_id
    ))
    session.execute(sa_delete(Entity).where(Entity.document_id == document_id))
    session.execute(sa_delete(Relationship).where(
        Relationship.document_id == document_id
    ))
    session.execute(sa_delete(Chunk).where(Chunk.document_id == document_id))
    session.execute(sa_delete(Memory).where(
        Memory.source_document_ids == f"[{document_id}]"
    ))
    session.delete(doc)
    session.commit()

    # Keep the in-memory plant-memory graph consistent with the DB.
    try:
        get_state().graph.rebuild(session, project_id)
    except Exception:
        pass  # graph rebuild is best-effort; deletion already persisted

    for path in [doc_path, *page_image_paths]:
        _unlink_quietly(path)


@router.get("/{document_id}/relationships", response_model=list[RelationshipOut])
def document_relationships(document_id: int, session: Session = Depends(get_session)):
    rows = session.exec(
        select(Relationship).where(Relationship.document_id == document_id)
        .order_by(Relationship.id)
    ).all()
    return [
        RelationshipOut(
            id=r.id,
            source_tag=r.source_tag,
            target_tag=r.target_tag,
            relationship_type=r.relationship_type,
            confidence=r.confidence,
            page_id=r.source_page_id,
        )
        for r in rows
    ]


@router.get("/entities/{entity_id}/detail", response_model=EntityDetailOut)
def entity_detail(entity_id: int, session: Session = Depends(get_session)):
    e = session.get(Entity, entity_id)
    if not e:
        raise HTTPException(status_code=404, detail="Entity not found")
    rels = session.exec(
        select(Relationship).where(
            (Relationship.source_tag == e.canonical_tag)
            | (Relationship.target_tag == e.canonical_tag)
        )
    ).all()
    doc = session.get(Document, e.document_id)
    page = session.get(DocumentPage, e.page_id)
    return EntityDetailOut(
        entity=_entity_out(e),
        connections=[
            RelationshipOut(
                id=r.id,
                source_tag=r.source_tag,
                target_tag=r.target_tag,
                relationship_type=r.relationship_type,
                confidence=r.confidence,
                page_id=r.source_page_id,
            )
            for r in rels
        ],
        source_document=doc.name if doc else "",
        page_number=page.page_number if page else 0,
        image_url=f"/api/pages/{e.page_id}/image" if e.page_id else "",
    )


def _entity_out(e: Entity) -> EntityOut:
    import json

    try:
        meta = json.loads(e.metadata_json or "{}")
    except ValueError:
        meta = {}
    return EntityOut(
        id=e.id,
        page_id=e.page_id,
        entity_type=e.entity_type,
        canonical_tag=e.canonical_tag,
        label=e.label,
        raw_text=e.raw_text,
        confidence=e.confidence,
        bbox=[e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
        metadata=meta,
    )


def _status_out(session: Session, doc: Document, progress: float = 0.0) -> IngestionStatusOut:
    ents = session.exec(select(Entity).where(Entity.document_id == doc.id)).all()
    rels = session.exec(select(Relationship).where(Relationship.document_id == doc.id)).all()
    pages = session.exec(select(DocumentPage).where(DocumentPage.document_id == doc.id)).all()
    chunks = session.exec(select(Chunk).where(Chunk.document_id == doc.id)).all()
    p = 0.0
    if doc.status == "ready":
        p = 1.0
    elif doc.status == "processing":
        p = max(progress, 0.1)
    elif doc.status == "failed":
        p = 0.0
    return IngestionStatusOut(
        document_id=doc.id,
        status=doc.status,
        stage=doc.stage,
        progress=p,
        pages=len(pages),
        entities=len(ents),
        relationships=len(rels),
        chunks=len(chunks),
        error=doc.error,
    )