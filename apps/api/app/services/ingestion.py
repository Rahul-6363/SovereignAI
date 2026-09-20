"""P&ID ingestion pipeline.

Deterministic enough that the UI can show progress:
  Upload -> File validation -> PDF/image normalization -> Page rendering
  -> Vision extraction -> Strict JSON validation -> Entity normalization
  -> Relationship inference -> Plant Memory write -> Chunk + embeddings
  -> Index ready
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from PIL import Image
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from app.config import Settings
from app.db import engine
from app.models import Chunk, Document, DocumentPage, Entity, Memory, Relationship
from app.services import audit
from app.services.embeddings import EmbeddingProvider
from app.services.graph_memory import GraphMemory
from app.services.ollama_gateway import OllamaGateway
from app.services.pid_parser import (
    is_image_mime,
    load_image,
    open_pdf,
    render_pdf_pages,
    safe_filename,
)
from app.services.vision_extractor import VisionExtractor

STAGES = [
    ("validating", 0.05, "File validation"),
    ("rendering", 0.12, "Pages rendered"),
    ("extracting", 0.45, "P&ID entities detected"),
    ("building_memory", 0.25, "Building Plant Memory"),
    ("indexing", 0.13, "Indexing evidence"),
]


def log_project(project_label: str, stage: str, message: str) -> None:
    print(f"[ingest:{project_label}] {stage}: {message}", flush=True)


class IngestionPipeline:
    def __init__(
        self,
        settings: Settings,
        gateway: OllamaGateway,
        extractor: VisionExtractor,
        embeddings: EmbeddingProvider,
        graph: GraphMemory,
    ):
        self.settings = settings
        self.gateway = gateway
        self.extractor = extractor
        self.embeddings = embeddings
        self.graph = graph
        # Document ids with an ingestion currently in flight (this process).
        self.active: set[int] = set()
        # The threads running them, so shutdown can wait rather than abandon.
        self._threads: list[threading.Thread] = []

    # ── idempotency ───────────────────────────────────────────
    def _reset_derived(self, session: Session, doc: Document) -> None:
        """Drop everything a previous run of THIS document produced.

        Ingestion is re-runnable (retry after a failure, re-extract with a
        better model). Without this, a second run appends a second copy of
        every page, entity, relationship and memory.
        """
        pages = session.exec(
            select(DocumentPage).where(DocumentPage.document_id == doc.id)
        ).all()
        stale_images = [p.image_path for p in pages if p.image_path]

        session.execute(sa_delete(Entity).where(Entity.document_id == doc.id))
        session.execute(
            sa_delete(Relationship).where(Relationship.document_id == doc.id)
        )
        session.execute(sa_delete(Chunk).where(Chunk.document_id == doc.id))
        session.execute(
            sa_delete(DocumentPage).where(DocumentPage.document_id == doc.id)
        )
        # Memories carry their source document ids as a JSON list.
        marker = f"[{doc.id}]"
        session.execute(
            sa_delete(Memory).where(
                Memory.project_id == doc.project_id,
                Memory.source_document_ids == marker,
            )
        )
        session.commit()

        for path in stale_images:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    # ── page preparation ──────────────────────────────────────
    def _prepare_pages(self, session: Session, doc: Document) -> tuple[list, object]:
        """Render pages, and keep the open PDF so the vector layer can read it.

        The render is what the UI shows and what a vision model sees; the PDF
        page itself still holds the exact text and geometry, which is strictly
        better input when it exists.
        """
        path = Path(doc.path)
        content = path.read_bytes()
        pdf = None
        if doc.mime_type == "application/pdf":
            images = render_pdf_pages(content)
            if self.settings.pid_use_vector_layer:
                pdf = open_pdf(content)
        elif is_image_mime(doc.mime_type):
            images = [load_image(content)]
        else:
            raise ValueError(f"Unsupported mime type: {doc.mime_type}")

        prepared = []
        for idx, img in enumerate(images, start=1):
            filename = f"doc{doc.id}-{safe_filename(Path(doc.name).stem)}-p{idx}.png"
            out = self.settings.page_path / filename
            img.save(out, format="PNG")
            page = DocumentPage(
                document_id=doc.id,
                page_number=idx,
                image_path=str(out),
                width=img.width,
                height=img.height,
            )
            session.add(page)
            session.commit()
            session.refresh(page)
            prepared.append((page.id, img))
        return prepared, pdf

    # ── persistence helpers ───────────────────────────────────
    def _persist_extraction(
        self,
        session: Session,
        doc: Document,
        page_id: int,
        extraction: dict,
        page_number: int,
    ) -> tuple[int, int]:
        entities = []
        for e in extraction.get("entities", []):
            ent = Entity(
                project_id=doc.project_id,
                page_id=page_id,
                document_id=doc.id,
                entity_type=e["type"],
                canonical_tag=e["tag"],
                label=e["label"],
                raw_text=e.get("raw_text", ""),
                confidence=float(e["confidence"]),
                bbox_x=e["bbox"][0],
                bbox_y=e["bbox"][1],
                bbox_w=e["bbox"][2],
                bbox_h=e["bbox"][3],
                metadata_json=json.dumps({
                    "model": extraction.get("_meta", {}).get("model", ""),
                    "path": extraction.get("_meta", {}).get("path", ""),
                    "source_layer": e.get("source_layer", ""),
                    "needs_review": bool(e.get("needs_review")),
                    "review_reasons": e.get("review_reasons", []),
                    "line_size_mm": e.get("line_size_mm"),
                }),
            )
            session.add(ent)
            entities.append(ent)
        session.commit()
        for ent in entities:
            session.refresh(ent)

        rel_count = 0
        for r in extraction.get("relationships", []):
            src = next((e for e in entities if e.canonical_tag == r["source"]), None)
            tgt = next((e for e in entities if e.canonical_tag == r["target"]), None)
            rel = Relationship(
                project_id=doc.project_id,
                document_id=doc.id,
                source_entity_id=src.id if src else 0,
                target_entity_id=tgt.id if tgt else 0,
                source_tag=r["source"],
                target_tag=r["target"],
                relationship_type=r["relation"],
                confidence=float(r["confidence"]),
                source_page_id=page_id,
                metadata_json=json.dumps({"method": r.get("method", "")}),
            )
            session.add(rel)
            rel_count += 1
        session.commit()
        return len(entities), rel_count
# ── chunking + embeddings ─────────────────────────────────
    async def _build_chunks(self, session: Session, doc: Document) -> int:
        existing = session.exec(select(Chunk).where(Chunk.document_id == doc.id)).all()
        for c in existing:
            session.delete(c)
        session.commit()

        entities = session.exec(
            select(Entity).where(Entity.document_id == doc.id)
            .order_by(Entity.page_id, Entity.id)
        ).all()
        rels = session.exec(
            select(Relationship).where(Relationship.document_id == doc.id)
            .order_by(Relationship.id)
        ).all()

        chunks_payload = []
        page_numbers = {
            p.id: p.page_number
            for p in session.exec(
                select(DocumentPage).where(DocumentPage.document_id == doc.id)
            ).all()
        }
        for e in entities:
            page_no = page_numbers.get(e.page_id, e.page_id)
            text = f"{e.canonical_tag} ({e.label}) is an {e.entity_type} on page {page_no}."
            chunks_payload.append(
                {
                    "page_id": e.page_id,
                    "text": text,
                    "bbox": [e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
                    "metadata": {"tag": e.canonical_tag, "type": e.entity_type},
                }
            )
        for r in rels:
            text = (
                f"{r.source_tag} has relationship {r.relationship_type} with {r.target_tag} "
                f"(confidence {r.confidence:.2f})."
            )
            chunks_payload.append(
                {
                    "page_id": r.source_page_id,
                    "text": text,
                    "bbox": [],
                    "metadata": {
                        "source": r.source_tag,
                        "relation": r.relationship_type,
                        "target": r.target_tag,
                    },
                }
            )
        pages = session.exec(
            select(DocumentPage).where(DocumentPage.document_id == doc.id)
        ).all()
        for p in pages:
            page_entities = [e for e in entities if e.page_id == p.id]
            summary = "Page " + str(p.page_number) + " contains: " + ", ".join(
                e.canonical_tag for e in page_entities
            )
            chunks_payload.append(
                {
                    "page_id": p.id,
                    "text": summary,
                    "bbox": [],
                    "metadata": {"page_summary": True},
                }
            )

        texts = [c["text"] for c in chunks_payload]
        vectors = await self.embeddings.embed_texts(texts) if texts else []
        for payload, vec in zip(chunks_payload, vectors):
            chunk = Chunk(
                project_id=doc.project_id,
                document_id=doc.id,
                page_id=payload["page_id"],
                text=payload["text"],
                bbox_json=json.dumps(payload["bbox"]),
                embedding_json=json.dumps(vec),
                embedding_id="",
                metadata_json=json.dumps(payload["metadata"]),
            )
            session.add(chunk)
        session.commit()
        return len(chunks_payload)

    def _build_memories(self, session: Session, doc: Document) -> int:
        entities = session.exec(
            select(Entity).where(Entity.document_id == doc.id).order_by(Entity.id)
        ).all()
        if not entities:
            return 0
        entity_ids = [str(e.id) for e in entities]
        summary = (
            f"{doc.name} describes {len(entities)} extracted plant entities: "
            + ", ".join(e.canonical_tag for e in entities[:12])
        )
        memory = Memory(
            project_id=doc.project_id,
            memory_type="document_summary",
            summary=summary,
            importance=0.8,
            source_entity_ids=json.dumps(entity_ids),
            source_document_ids=json.dumps([doc.id]),
        )
        session.add(memory)
        session.commit()
        return 1
# ── main entry ─────────────────────────────────────────────
    def spawn(self, document_id: int) -> None:
        """Start an ingestion on its own thread and return immediately.

        This must NOT run on the API event loop. Ingestion is dominated by
        CPU-bound work — PDF rasterising, OCR, OpenCV — which never yields.
        Scheduled as an asyncio task (or a FastAPI async BackgroundTask) it
        blocks the single uvicorn worker outright, so every other request,
        including the UI's own `/status` poll, is starved until the page has
        finished. That is exactly the "upload sits dead for fifteen minutes,
        then a manual refresh shows the result" report: the extraction had
        been done for a while, but nothing could be served to say so.

        A dedicated thread with its own event loop keeps the API answering
        while it works, so progress is visible as it happens.
        """
        if document_id in self.active:
            return  # already in flight; do not start a second pass
        self.active.add(document_id)

        def _worker() -> None:
            try:
                asyncio.run(self._run_owned(document_id))
            except Exception as exc:  # pragma: no cover - defensive
                log_project(f"document-{document_id}", "failed", str(exc)[:200])
            finally:
                self.active.discard(document_id)

        thread = threading.Thread(
            target=_worker, name=f"ingest-{document_id}", daemon=True
        )
        self._threads = [t for t in self._threads if t.is_alive()]
        self._threads.append(thread)
        thread.start()

    def join_active(self, timeout: float = 30.0) -> None:
        """Wait for in-flight ingestions, for a bounded time.

        Called on shutdown. A run abandoned mid-flight leaves its document
        stuck on `processing`, which the next start then has to detect and
        recover; waiting briefly avoids creating that state in the first
        place. The threads are daemons, so a genuinely stuck run still cannot
        prevent the process exiting.
        """
        deadline = time.monotonic() + timeout
        for thread in list(self._threads):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    async def _run_owned(self, document_id: int) -> dict:
        """Run on the worker thread's own loop, with its own HTTP resources.

        `httpx.AsyncClient` binds to the event loop that first uses it, so the
        shared gateway — created on the API's loop — cannot be driven from
        this thread. Sharing it appears to work until the embedding call, then
        fails in ways that surface as a broken shutdown rather than as an
        error here. The thread gets its own gateway and closes it when done.
        """
        import copy

        from app.services.embeddings import EmbeddingProvider as _Embeddings
        from app.services.vision_extractor import VisionExtractor as _Extractor

        gateway = OllamaGateway(self.settings)
        # A shallow copy, not mutation of self: two documents can ingest at
        # once, and swapping attributes on the shared instance would have each
        # thread overwriting the other's client. The graph and settings are
        # deliberately still shared.
        worker = copy.copy(self)
        worker.gateway = gateway
        worker.embeddings = _Embeddings(
            self.settings, gateway, dim=self.settings.embed_dim
        )
        worker.extractor = _Extractor(self.settings, gateway)
        try:
            return await worker._run_impl(document_id)
        finally:
            try:
                await gateway.close()
            except Exception:
                pass

    async def run(self, document_id: int) -> dict:
        """Await an ingestion to completion (tests, scripts, verify harness)."""
        self.active.add(document_id)
        try:
            return await self._run_impl(document_id)
        finally:
            self.active.discard(document_id)

    async def _run_impl(self, document_id: int) -> dict:
        with Session(engine) as session:
            doc = session.get(Document, document_id)
            if doc is None:
                raise ValueError(f"document {document_id} not found")
            doc.status = "processing"
            doc.stage = "validating"
            session.add(doc)
            session.commit()
            session.refresh(doc)
            project_label = f"project-{doc.project_id}/{doc.name}"

            try:
                self._reset_derived(session, doc)
                pages, pdf = self._prepare_pages(session, doc)
                doc.page_count = len(pages)
                doc.stage = "rendering"
                session.add(doc)
                session.commit()
                log_project(project_label, "rendering", f"{len(pages)} pages")

                total_e = 0
                total_r = 0
                extract_notes: list[str] = []
                for idx, (page_id, img) in enumerate(pages, start=1):
                    # Page-level stage text so a long multi-page sheet shows
                    # movement rather than one motionless "extracting".
                    doc.stage = (
                        "extracting"
                        if len(pages) == 1
                        else f"extracting:{idx}/{len(pages)}"
                    )
                    session.add(doc)
                    session.commit()
                    log_project(project_label, "extracting", f"page {idx}")
                    pdf_page = None
                    if pdf is not None and idx - 1 < pdf.page_count:
                        pdf_page = pdf[idx - 1]
                    extraction = await self.extractor.extract_page(
                        img, doc.name, page_number=idx, pdf_page=pdf_page
                    )
                    note = (extraction.get("_meta") or {}).get("note")
                    if note:
                        extract_notes.append(str(note))
                    ne, nr = self._persist_extraction(session, doc, page_id, extraction, idx)
                    total_e += ne
                    total_r += nr
                    log_project(
                        project_label,
                        "extracting",
                        f"page {idx}: {ne} entities, {nr} relations",
                    )

                doc.stage = "building_memory"
                session.add(doc)
                session.commit()
                self.graph.rebuild(session, doc.project_id)
                log_project(project_label, "building_memory", f"graph {self.graph.summary()}")

                doc.stage = "indexing"
                session.add(doc)
                session.commit()
                await self.embeddings.refresh_mode()
                n_chunks = await self._build_chunks(session, doc)
                n_mem = self._build_memories(session, doc)
                log_project(project_label, "indexing", f"{n_chunks} chunks, {n_mem} memories")

                if pdf is not None:
                    pdf.close()
                    pdf = None

                doc.status = "ready"
                doc.stage = "index_ready"
                # Zero-entity extractions are visible in the UI instead of
                # silently showing a green "ready" with empty memory.
                doc.error = "; ".join(extract_notes)[:480] if extract_notes else ""
                session.add(doc)
                session.commit()
                audit.record_event(
                    user_action="ingest",
                    model="deterministic-golden",
                    result_status="ok",
                    retrieval_count=total_e + total_r,
                )
                return {
                    "status": "ready",
                    "entities": total_e,
                    "relationships": total_r,
                    "chunks": n_chunks,
                    "memories": n_mem,
                }
            except Exception as exc:
                if pdf is not None:
                    try:
                        pdf.close()
                    except Exception:
                        pass
                doc.status = "failed"
                doc.stage = "error"
                doc.error = str(exc)[:500]
                session.add(doc)
                session.commit()
                log_project(project_label, "failed", str(exc))
                audit.record_event(
                    user_action="ingest",
                    tool_name="ingestion_pipeline",
                    result_status="failed",
                )
                raise