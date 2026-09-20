"""Embedding provider — Ollama `nomic-embed-text` with a deterministic
offline fallback so vector search works even before models are pulled.

The fallback is a count-vectorizer-style hashed character n-gram space,
normalized to unit length. It gives the demo full offline parity.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading

import numpy as np

from app.config import Settings
from app.services.ollama_gateway import OllamaGateway

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class EmbeddingProvider:
    def __init__(self, settings: Settings, gateway: OllamaGateway, dim: int = 384):
        self.settings = settings
        self.gateway = gateway
        self.dim = dim
        self._lock = threading.Lock()
        self.mode = "local-fallback"

    async def refresh_mode(self) -> str:
        """Detect whether the configured embed model is available locally."""
        try:
            if await self.gateway.model_installed(self.settings.ollama_embed_model):
                self.mode = self.settings.ollama_embed_model
            else:
                self.mode = "local-fallback"
        except Exception:
            self.mode = "local-fallback"
        return self.mode

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.mode != "local-fallback":
            emb = await self.gateway.embed(texts, self.mode)
            if emb:
                return emb
        return [self._local_embed(t) for t in texts]

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed_texts([query]))[0]

    # ── deterministic local fallback ──────────────────────────
    def _ngrams(self, text: str) -> list[str]:
        tokens = _TOKEN_RE.findall(text.lower())
        grams: list[str] = []
        for tok in tokens:
            tok = tok.strip("0123456789")
            padded = f"#{tok}#"
            for n in (2, 3):
                for i in range(len(padded) - n + 1):
                    grams.append(f"{n}:{padded[i:i+n]}")
        return grams

    def _local_embed(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float32)
        with self._lock:
            for gram in self._ngrams(text):
                h = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if h[4] % 2 == 0 else -1.0
                vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return [float(v) for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)