"""App-level singletons shared by routers (FastAPI dependency style)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import Settings, get_settings


@dataclass
class AppState:
    settings: Settings
    gateway: object  # OllamaGateway
    graph: object    # GraphMemory
    embeddings: object
    extractor: object
    retriever: object
    answer_generator: object
    pipeline: object


_state: Optional[AppState] = None


def init_state(state: AppState) -> None:
    global _state
    _state = state


def get_state() -> AppState:
    if _state is None:
        raise RuntimeError("Application state not initialised")
    return _state


def app_settings() -> Settings:
    return get_settings()