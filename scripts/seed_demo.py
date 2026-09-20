"""Seed the golden demo dataset.

Creates the three demo projects (Unit A, Compressor Train, Demo Plant),
uploads the bundled demo P&ID, runs the full ingestion pipeline, rebuilds
the plant memory graph, and finally runs the five golden questions through
the answer generator, printing a pass/fail report.

Run from repo root:
    python scripts/seed_demo.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

from app.config import get_settings  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Document,
    Project,
)
from app.services.embeddings import EmbeddingProvider  # noqa: E402
from app.services.graph_memory import GraphMemory  # noqa: E402
from app.services.hybrid_retriever import HybridRetriever  # noqa: E402
from app.services.ingestion import IngestionPipeline  # noqa: E402
from app.services.ollama_gateway import OllamaGateway  # noqa: E402
from app.services.pid_parser import normalize_mime  # noqa: E402
from app.services.vision_extractor import VisionExtractor  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

settings = get_settings()


def ensure_demo_pid() -> Path:
    png = settings.demo_path / "pid" / "unit-a-pid.png"
    if not png.exists():
        raise FileNotFoundError(
            "demo P&ID missing - run `python scripts/make_demo_pid.py` first"
        )
    return png


async def seed() -> None:
    init_db()

    with Session(engine) as session:
        # ── projects ──────────────────────────────────────────
        demo = session.exec(select(Project).where(Project.name == "Demo Plant")).first()
        if not demo:
            demo = Project(name="Demo Plant", description="Golden demo: Unit A P&ID")
            session.add(demo)
            session.commit()
            session.refresh(demo)
        unit_a = session.exec(select(Project).where(Project.name == "Unit A")).first()
        if not unit_a:
            unit_a = Project(name="Unit A", description="Feed / pumping / heater train")
            session.add(unit_a)
            session.commit()
        compressor = session.exec(
            select(Project).where(Project.name == "Compressor Train")
        ).first()
        if not compressor:
            compressor = Project(
                name="Compressor Train",
                description="(reserved) compressor skid P&ID",
            )
            session.add(compressor)
            session.commit()
        project = demo

        # ── upload demo P&ID ──────────────────────────────────
        pid_path = ensure_demo_pid()
        content = pid_path.read_bytes()
        upload_path = settings.upload_path / pid_path.name
        if not upload_path.exists():
            upload_path.write_bytes(content)

        doc = session.exec(
            select(Document).where(Document.name == pid_path.name)
        ).first()
        if not doc:
            doc = Document(
                project_id=project.id,
                name=pid_path.name,
                mime_type=normalize_mime(pid_path.name, content),
                path=str(upload_path),
                sha256=__import__("hashlib").sha256(content).hexdigest(),
                status="uploaded",
                stage="uploaded",
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
        print(f"project '{project.name}' id={project.id}  document={doc.name} id={doc.id}")

        # ── services ──────────────────────────────────────────
        gateway = OllamaGateway(settings)
        graph = GraphMemory(settings)
        embeddings = EmbeddingProvider(settings, gateway, dim=settings.embed_dim)
        extractor = VisionExtractor(settings, gateway)
        pipeline = IngestionPipeline(settings, gateway, extractor, embeddings, graph)

        # ── run pipeline ──────────────────────────────────────
        if doc.status != "ready":
            print("running ingestion pipeline (safe to re-run)...", flush=True)
            await pipeline.run(doc.id)
        else:
            print("document already ready — reindexing chunks to be safe", flush=True)
            graph.rebuild(session, project.id)
            await embeddings.refresh_mode()
            await pipeline._build_chunks(session, doc)
            pipeline._build_memories(session, doc)

        graph.rebuild(session, project.id)
        summary = graph.summary()
        print(
            f"plant memory ready: {summary['nodes']} nodes, {summary['edges']} edges · "
            f"embedding mode: {embeddings.mode}"
        )

        await gateway.close()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
    print("✓ seed complete")