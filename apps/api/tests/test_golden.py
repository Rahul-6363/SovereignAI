"""Golden extraction + golden question tests (README section 28).

Golden extraction: replays the hand-verified `expected/entities.json` and
asserts precision/recall + bbox validity against a deterministic pass of
the bundled demo P&ID.

Golden questions: asserts that answers contain expected tags, expected
relations and no forbidden hallucinated tags (offline template engine).
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import namedtuple
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "apps" / "api"))
sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Chunk,
    Document,
    DocumentPage,
    Entity,
    Memory,
    Project,
    Relationship,
)
from sqlalchemy import delete as sa_delete  # noqa: E402
from app.services.embeddings import EmbeddingProvider  # noqa: E402
from app.services.graph_memory import GraphMemory  # noqa: E402
from app.services.hybrid_retriever import HybridRetriever  # noqa: E402
from app.services.ingestion import IngestionPipeline  # noqa: E402
from app.services.ollama_gateway import OllamaGateway  # noqa: E402
from app.services.pid_parser import normalize_mime  # noqa: E402
from app.services.vision_extractor import VisionExtractor  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

settings = get_settings()


@pytest.fixture(scope="module")
def demo_env():
    """Ingest the demo P&ID once into an isolated test project."""
    init_db()
    with Session(engine) as session:
        project = Project(name="Golden Test Project")
        session.add(project)
        session.commit()
        session.refresh(project)
        # Capture scalar values BEFORE the second commit below: commit() expires
        # all instances, and accessing .id after the session closes would raise
        # DetachedInstanceError.
        project_id = project.id

        pid_path = settings.demo_path / "pid" / "unit-a-pid.png"
        content = pid_path.read_bytes()
        upload = settings.upload_path / f"golden-test-{project_id}.png"
        upload.write_bytes(content)
        doc = Document(
            project_id=project_id,
            name="unit-a-pid.png",
            mime_type=normalize_mime("unit-a-pid.png", content),
            path=str(upload),
            sha256="golden",
            status="uploaded",
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)
        doc_id = doc.id

    gateway = OllamaGateway(settings)
    graph = GraphMemory(settings)
    embeddings = EmbeddingProvider(settings, gateway, dim=settings.embed_dim)
    extractor = VisionExtractor(settings, gateway)
    pipeline = IngestionPipeline(settings, gateway, extractor, embeddings, graph)
    asyncio.run(pipeline.run(doc_id))

    with Session(engine) as session:
        entities = session.exec(select(Entity).where(Entity.document_id == doc_id)).all()
        rels = session.exec(select(Relationship).where(Relationship.document_id == doc_id)).all()
        _EntityRow = namedtuple(
            "EntityRow",
            "canonical_tag entity_type bbox_x bbox_y bbox_w bbox_h confidence",
        )
        _RelRow = namedtuple("RelRow", "source_tag relationship_type target_tag confidence")
        entity_rows = [
            _EntityRow(
                e.canonical_tag, e.entity_type, e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h, e.confidence
            )
            for e in entities
        ]
        rel_rows = [
            _RelRow(r.source_tag, r.relationship_type, r.target_tag, r.confidence) for r in rels
        ]
    yield {
        "project_id": project_id,
        "doc_id": doc_id,
        "entities": entity_rows,
        "rels": rel_rows,
    }

    # Tear down EVERYTHING the ingest produced. Deleting only the document and
    # the project left entities, relationships, chunks, pages and memories
    # behind — invisible orphans, since SQLite does not enforce the FKs.
    with Session(engine) as session:
        for model, column in (
            (Chunk, Chunk.document_id),
            (Relationship, Relationship.document_id),
            (Entity, Entity.document_id),
            (DocumentPage, DocumentPage.document_id),
        ):
            session.execute(sa_delete(model).where(column == doc_id))
        session.execute(sa_delete(Memory).where(Memory.project_id == project_id))
        session.execute(sa_delete(Document).where(Document.id == doc_id))
        session.execute(sa_delete(Project).where(Project.id == project_id))
        session.commit()
    engine.dispose()


def _load_expected() -> dict:
    p = settings.demo_path / "expected" / "entities.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ── golden extraction ─────────────────────────────────────────
def test_golden_entity_precision_recall(demo_env):
    expected = _load_expected()
    exp_tags = {e["tag"] for e in expected["entities"]}
    got_tags = {e.canonical_tag for e in demo_env["entities"]}
    overlap = got_tags & exp_tags
    precision = len(overlap) / len(got_tags) if got_tags else 0
    recall = len(overlap) / len(exp_tags) if exp_tags else 0
    assert precision == pytest.approx(1.0, abs=0.08), f"precision={precision:.2f}"
    assert recall >= 0.9, f"recall={recall:.2f}"


def test_golden_relationship_precision_recall(demo_env):
    expected = _load_expected()
    exp = {(r["source"], r["relation"], r["target"]) for r in expected["relationships"]}
    got = {(r.source_tag, r.relationship_type, r.target_tag) for r in demo_env["rels"]}
    overlap = got & exp
    precision = len(overlap) / len(got) if got else 0
    recall = len(overlap) / len(exp) if exp else 0
    assert precision >= 0.9, f"precision={precision:.2f}"
    assert recall >= 0.9, f"recall={recall:.2f}"


def test_bbox_validity(demo_env):
    for e in demo_env["entities"]:
        assert 0.0 <= e.bbox_x <= 1.0
        assert 0.0 <= e.bbox_y <= 1.0
        assert 0.0 <= e.bbox_w <= 1.0
        assert 0.0 <= e.bbox_h <= 1.0
# ── golden questions (offline template engine) ────────────────
def test_golden_questions(demo_env):
    gq = json.loads(
        (settings.demo_path / "expected" / "golden-questions.json").read_text(encoding="utf-8")
    )
    gateway = OllamaGateway(settings)
    graph = GraphMemory(settings)
    embeddings = EmbeddingProvider(settings, gateway, dim=settings.embed_dim)
    retriever = HybridRetriever(settings, graph, embeddings)

    from app.services.answer_generator import AnswerGenerator

    gen = AnswerGenerator(settings, gateway, retriever, graph)

    def ask(project_id: int, question: str) -> str:
        parts = []

        with Session(engine) as session:
            graph.rebuild(session, project_id)

            async def _run():
                async for ev in gen.stream_chat(
                    session, project_id, question, top_k=10, session_id="test"
                ):
                    if ev["type"] == "token":
                        parts.append(ev["text"])

            asyncio.run(_run())
        return "".join(parts)

    for item in gq["questions"]:
        answer = ask(demo_env["project_id"], item["question"])
        lower = answer.lower()
        for tag in item["expected_tags"]:
            assert tag in answer or tag.lower() in lower, (
                f"Q: {item['question']} — expected tag '{tag}' missing in: {answer[:200]}"
            )
        for forbidden in item["forbidden_tags"]:
            assert forbidden not in answer, (
                f"Q: {item['question']} — forbidden tag '{forbidden}' hallucinated"
            )
    engine.dispose()