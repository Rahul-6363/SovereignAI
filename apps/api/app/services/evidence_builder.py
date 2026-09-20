"""Evidence builder — converts raw retrieval results into the model-ready
EvidencePacket contract (README section 12)."""
from __future__ import annotations

import json

from sqlmodel import Session, col, select

from app.services.confidence import merge_confidences
from app.services.graph_memory import GraphMemory


def build_evidence_packet(
    session: Session,
    project_id: int,
    query: str,
    graph: GraphMemory,
    retrieval_results: list[dict],
) -> dict:
    """Produce an EvidencePacket dict from ranked retrieval results."""
    answer_context = []

    for item in retrieval_results:
        source_type = item.get("source", "chunk")
        if source_type == "entity":
            answer_context.append(
                {
                    "source_type": "pid",
                    "entity": item.get("tag"),
                    # document_id is resolved from page_id by
                    # attach_document_meta; entity_id is NOT a document id.
                    "document_id": None,
                    "entity_id": item.get("entity_id"),
                    "page": item.get("page_id"),
                    "bbox": item.get("bbox"),
                    "text": item.get("text", ""),
                    "confidence": item.get("confidence"),
                }
            )
        elif source_type == "graph":
            # A graph edge was extracted from a specific drawing page. Dropping
            # that here leaves a deliverable citing a connection with no source
            # — the one thing an engineering document may not do.
            answer_context.append(
                {
                    "source_type": "graph",
                    "entity": item.get("from"),
                    "relation": item.get("relation"),
                    "target": item.get("tag"),
                    "confidence": item.get("confidence"),
                    "page": None,
                }
            )
        elif source_type == "chunk":
            answer_context.append(
                {
                    "source_type": "chunk",
                    "document_id": item.get("chunk_id"),
                    "page": item.get("page_id"),
                    "bbox": item.get("bbox") if item.get("bbox") else None,
                    "text": item.get("text", ""),
                    "confidence": item.get("confidence"),
                }
            )
        elif source_type == "document":
            answer_context.append(
                {
                    "source_type": "document",
                    "document_id": item.get("document_id"),
                    "entity": item.get("tag"),
                    "text": item.get("text", ""),
                    "confidence": item.get("confidence"),
                }
            )

    _attach_graph_provenance(session, project_id, answer_context)

    confidences = [float(c["confidence"]) for c in answer_context if c.get("confidence")]
    confidence = merge_confidences(confidences) if confidences else 0.0

    return {
        "answer_context": answer_context[:24],
        "confidence": confidence,
        "query_intent": "",
        "retrieved_from": build_retrieval_summary(retrieval_results),
    }


def _attach_graph_provenance(
    session: Session, project_id: int, answer_context: list[dict]
) -> None:
    """Trace each graph edge back to the drawing page it was extracted from."""
    from app.models import Relationship

    wanted = {
        (c.get("entity"), c.get("relation"), c.get("target"))
        for c in answer_context
        if c.get("source_type") == "graph"
    }
    if not wanted:
        return
    rows = session.exec(
        select(Relationship).where(Relationship.project_id == project_id)
    ).all()
    by_triple = {
        (r.source_tag, r.relationship_type, r.target_tag): r for r in rows
    }
    for c in answer_context:
        if c.get("source_type") != "graph":
            continue
        rel = by_triple.get((c.get("entity"), c.get("relation"), c.get("target")))
        if rel is None:
            continue
        # `page` here is a page_id; attach_document_meta turns it into a page
        # number and resolves the document name alongside it.
        if rel.source_page_id:
            c["page"] = rel.source_page_id
        if rel.document_id:
            c["document_id"] = rel.document_id


def build_retrieval_summary(results: list[dict]) -> str:
    counts = {}
    for r in results:
        counts[r.get("source", "?")] = counts.get(r.get("source", "?"), 0) + 1
    parts = [f"{k}:{v}" for k, v in counts.items()]
    return ", ".join(parts) if parts else "none"


def attach_document_meta(session: Session, packet: dict) -> dict:
    """Fill in document names/pages for pid sources (page_id -> page_number)."""
    from app.models import Document, DocumentPage

    page_ids = {c.get("page") for c in packet["answer_context"] if c.get("page")}
    page_map: dict[int, dict] = {}
    doc_names: dict[int, str] = {}
    if page_ids:
        stmt = select(DocumentPage).where(col(DocumentPage.id).in_(list(page_ids)))
        for p in session.exec(stmt).all():
            page_map[p.id] = {
                "page_number": p.page_number,
                "document_id": p.document_id,
            }
        doc_ids = {v["document_id"] for v in page_map.values()}
        if doc_ids:
            docs = session.exec(
                select(Document).where(col(Document.id).in_(list(doc_ids)))
            ).all()
            doc_names = {d.id: d.name for d in docs}

    # Any source that already knows its document id can still be named.
    leftover_ids = {
        c["document_id"] for c in packet["answer_context"]
        if c.get("document_id") and c["document_id"] not in doc_names
    }
    if leftover_ids:
        for d in session.exec(
            select(Document).where(col(Document.id).in_(list(leftover_ids)))
        ).all():
            doc_names[d.id] = d.name

    for c in packet["answer_context"]:
        if not c.get("document") and c.get("document_id") in doc_names:
            c["document"] = doc_names[c["document_id"]]
        info = page_map.get(c.get("page"))
        if not info:
            continue
        c["page"] = info["page_number"]
        c["document_id"] = info["document_id"]
        # The UI cites by name; without this every source read "unknown".
        c.setdefault("document", None)
        c["document"] = doc_names.get(info["document_id"]) or c.get("document")
    return packet