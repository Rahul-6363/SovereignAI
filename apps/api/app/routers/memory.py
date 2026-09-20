"""Plant Memory routes — graph, entity detail, memories, summary."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.deps import get_state
from app.models import Entity, Memory, Project
from app.schemas import EntityDetailOut, EntityOut, MemoryOut, MemoryGraphOut
from app.services.graph_memory import to_graph_payload

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/{project_id}/graph", response_model=MemoryGraphOut)
def memory_graph(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    state = get_state()
    graph = state.graph.rebuild(session, project_id)
    return MemoryGraphOut(**to_graph_payload(graph, project_id))


@router.get("/{project_id}/entities/{tag}", response_model=EntityDetailOut)
def memory_entity(
    project_id: int, tag: str, session: Session = Depends(get_session)
):
    from app.services.entity_normalizer import normalize_tag
    from app.models import Document, DocumentPage, Relationship

    canonical = normalize_tag(tag)
    state = get_state()
    state.graph.rebuild(session, project_id)
    e = session.exec(
        select(Entity).where(
            Entity.project_id == project_id,
            Entity.canonical_tag == canonical,
        )
    ).first()
    if not e:
        raise HTTPException(status_code=404, detail=f"Entity '{tag}' not found")

    rels = session.exec(
        select(Relationship).where(
            (Relationship.project_id == project_id)
            & (
                (Relationship.source_tag == canonical)
                | (Relationship.target_tag == canonical)
            )
        )
    ).all()
    doc = session.get(Document, e.document_id)
    page = session.get(DocumentPage, e.page_id)
    return EntityDetailOut(
        entity=EntityOut(
            id=e.id,
            page_id=e.page_id,
            entity_type=e.entity_type,
            canonical_tag=e.canonical_tag,
            label=e.label,
            raw_text=e.raw_text,
            confidence=e.confidence,
            bbox=[e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
        ),
        connections=[
            {
                "id": r.id,
                "source_tag": r.source_tag,
                "target_tag": r.target_tag,
                "relationship_type": r.relationship_type,
                "confidence": r.confidence,
                "page_id": r.source_page_id,
            }
            for r in rels
        ],
        source_document=doc.name if doc else "",
        page_number=page.page_number if page else 0,
        image_url=f"/api/pages/{e.page_id}/image" if e.page_id else "",
    )


@router.get("/{project_id}/memories", response_model=list[MemoryOut])
def memory_list(project_id: int, session: Session = Depends(get_session)):
    rows = session.exec(
        select(Memory).where(Memory.project_id == project_id).order_by(Memory.id.desc())
    ).all()
    return [
        MemoryOut(id=m.id, memory_type=m.memory_type, summary=m.summary, importance=m.importance)
        for m in rows
    ]


@router.get("/{project_id}/summary")
def memory_summary(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    entities = session.exec(
        select(Entity).where(Entity.project_id == project_id)
    ).all()
    tags = sorted(set(e.canonical_tag for e in entities))
    return {"project_id": project_id, "entity_count": len(entities), "tags": tags}