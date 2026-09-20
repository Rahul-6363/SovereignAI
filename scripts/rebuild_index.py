"""Rebuild the vector index from persisted chunks in each project.

Recomputes embeddings for every chunk using the configured embed model
(or the deterministic local fallback when the model is unavailable).

Run from repo root:
    python scripts/rebuild_index.py [project_id]
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
from app.models import Chunk, Project  # noqa: E402
from app.services.embeddings import EmbeddingProvider  # noqa: E402
from app.services.ollama_gateway import OllamaGateway  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

settings = get_settings()


async def rebuild(project_id: int | None = None) -> None:
    init_db()
    gateway = OllamaGateway(settings)
    embeddings = EmbeddingProvider(settings, gateway, dim=settings.embed_dim)
    mode = await embeddings.refresh_mode()
    print(f"embedding mode: {mode}")

    with Session(engine) as session:
        if project_id is not None:
            projects = [session.get(Project, project_id)]
        else:
            projects = session.exec(select(Project)).all()
        total = 0
        for p in projects:
            if p is None:
                continue
            chunks = session.exec(select(Chunk).where(Chunk.project_id == p.id)).all()
            texts = [c.text for c in chunks]
            if not texts:
                print(f"project {p.id}: no chunks")
                continue
            vectors = await embeddings.embed_texts(texts)
            for c, vec in zip(chunks, vectors):
                c.embedding_json = json.dumps(vec)
            session.commit()
            total += len(chunks)
            print(f"project {p.id} '{p.name}': {len(chunks)} chunks re-embedded")
    print(f"done — {total} chunks rebuilt")
    await gateway.close()
    engine.dispose()


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(rebuild(int(arg) if arg else None))