"""Meshcore API — FastAPI entrypoint.

Wires the model gateway, plant memory graph, hybrid retrieval and the
grounded chat pipeline into one sovereign, local-only service.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import engine, init_db
from app.deps import AppState, init_state
from app.routers import (
    chat,
    deliverables,
    documents,
    health,
    memory,
    projects,
    trust,
)
from app.services.answer_generator import AnswerGenerator
from app.services.embeddings import EmbeddingProvider
from app.services.graph_memory import GraphMemory
from app.services.hybrid_retriever import HybridRetriever
from app.services.ingestion import IngestionPipeline
from app.services.ollama_gateway import OllamaGateway
from app.services.vision_extractor import VisionExtractor

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    gateway = OllamaGateway(settings)
    graph = GraphMemory(settings)
    embeddings = EmbeddingProvider(settings, gateway, dim=settings.embed_dim)
    extractor = VisionExtractor(settings, gateway)
    retriever = HybridRetriever(settings, graph, embeddings)
    answer_generator = AnswerGenerator(settings, gateway, retriever, graph)
    pipeline = IngestionPipeline(settings, gateway, extractor, embeddings, graph)

    init_state(
        AppState(
            settings=settings,
            gateway=gateway,
            graph=graph,
            embeddings=embeddings,
            extractor=extractor,
            retriever=retriever,
            answer_generator=answer_generator,
            pipeline=pipeline,
        )
    )
    try:
        yield
    finally:
        # Let an in-flight ingest finish before the engine goes away, or its
        # document is left stuck on "processing" for the next start to find.
        pipeline.join_active(timeout=30.0)
        await gateway.close()
        engine.dispose()


app = FastAPI(
    title="Meshcore API",
    description=(
        "Sovereign on-premise agentic AI workbench — P&ID to Plant Memory to "
        "grounded answers."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(trust.router)
app.include_router(deliverables.router)


@app.get("/")
def root():
    return {
        "service": "meshcore",
        "status": "local",
        "docs": "/docs",
        "health": "/api/health",
    }