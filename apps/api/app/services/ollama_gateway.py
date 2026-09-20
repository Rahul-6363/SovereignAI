"""Ollama model gateway.

All LLM traffic flows through this single module. The gateway:
- probes availability and local model lists
- streams chat completions (SSE from /api/chat)
- generates embeddings (/api/embed)
- keeps latency metrics for the trust panel

Never hard-code a model name in a feature — read models from settings.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

import httpx

from app.config import Settings


@dataclass
class OllamaLatency:
    last_chat_ms: float = 0.0
    last_embed_ms: float = 0.0
    total_chat_sec: float = 0.0
    total_embed_sec: float = 0.0
    chat_calls: int = 0
    embed_calls: int = 0
    history: list = field(default_factory=list)

    def record(self, kind: str, ms: float) -> None:
        if kind == "chat":
            self.last_chat_ms = ms
            self.total_chat_sec += ms / 1000
            self.chat_calls += 1
        else:
            self.last_embed_ms = ms
            self.total_embed_sec += ms / 1000
            self.embed_calls += 1
        self.history.append({"kind": kind, "ms": round(ms, 1)})
        self.history = self.history[-100:]


def _round_up_ctx(tokens: int) -> int:
    """Next power-of-two-ish window that holds `tokens`.

    Ollama allocates the KV cache from num_ctx, so asking for an odd exact
    number costs memory for nothing; the usual sizes are what the runtimes
    are tuned for.
    """
    for size in (2048, 4096, 8192, 16384, 32768):
        if tokens <= size:
            return size
    return 32768


class OllamaGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=3.0))
        self.latency = OllamaLatency()
        self._models_cache = None
        self._cache_at = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    # ── helpers ────────────────────────────────────────────────
    async def _get(self, path: str) -> httpx.Response:
        return await self._client.get(f"{self.base_url}{path}")

    async def _post(self, path: str, payload: dict) -> httpx.Response:
        return await self._client.post(f"{self.base_url}{path}", json=payload)

    async def is_available(self) -> bool:
        try:
            r = await self._client.get(f"{self.base_url}/api/tags", timeout=4.0)
            return r.status_code == 200
        except Exception:
            return False

    async def _refresh_models(self) -> dict:
        if self._models_cache and time.time() - self._cache_at < 10:
            return self._models_cache
        try:
            r = await self._get("/api/tags")
            if r.status_code == 200:
                self._models_cache = r.json()
                self._cache_at = time.time()
        except Exception:
            self._models_cache = {"models": []}
        return self._models_cache

    async def local_models(self) -> list:
        data = await self._refresh_models()
        return [m.get("name", "") for m in data.get("models", [])]

    async def model_installed(self, name: str) -> bool:
        models = await self.local_models()
        if not models:
            return False
        if name in models:
            return True
        base = name.split(":")[0]
        return any(m == base or m.startswith(f"{base}:") for m in models)

    async def model_sizes(self) -> dict:
        data = await self._refresh_models()
        out = {}
        for m in data.get("models", []):
            size = int(m.get("size", 0))
            mb = size / (1024 * 1024)
            out[m.get("name", "")] = f"{mb:.0f} MB" if mb < 1024 else f"{mb / 1024:.1f} GB"
        return out

    # ── chat streaming ─────────────────────────────────────────
    async def chat_stream(
        self,
        messages: list,
        model: str,
        options: Optional[dict] = None,
    ):
        """Yield incremental text tokens from /api/chat stream=true."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        if options:
            payload["options"] = options
        t0 = time.perf_counter()
        try:
            async with self._client.stream(
                "POST", f"{self.base_url}/api/chat", json=payload, timeout=600.0
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "error" in obj:
                        raise RuntimeError(str(obj["error"]))
                    delta = obj.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if obj.get("done"):
                        break
        finally:
            ms = (time.perf_counter() - t0) * 1000
            self.latency.record("chat", ms)

    async def complete(
        self,
        prompt: str,
        model: str,
        system: str = "",
        temperature: float = 0.2,
        num_predict: int | None = None,
        num_ctx: int | None = None,
    ) -> str:
        """One non-streaming completion.

        `num_predict` overrides the global answer cap. Chat answers are kept
        short on purpose, but structured output is different: a JSON table cut
        off at the default cap is not a short table, it is unparseable.

        `num_ctx` is passed through when the caller has budgeted the prompt.
        Left unset, Ollama picks its own window and truncates anything longer
        than it without saying so; every caller here that builds a prompt of
        non-trivial size sets it, and the default keeps enough room for the
        requested output rather than silently competing with it.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        from app.services.context import estimate_messages, model_window

        predict = num_predict or self.settings.ollama_num_predict
        if num_ctx is None:
            needed = estimate_messages(messages) + int(predict) + 128
            num_ctx = max(model_window(model), _round_up_ctx(needed))
        chunks = []
        async for token in self.chat_stream(
            messages,
            model,
            {
                "temperature": temperature,
                "num_predict": predict,
                "num_ctx": int(num_ctx),
            },
        ):
            chunks.append(token)
        return "".join(chunks)

    # ── embeddings ─────────────────────────────────────────────
    async def embed(self, texts: list, model: str):
        """Return list of embeddings or None when the model is unavailable."""
        if not texts:
            return None
        t0 = time.perf_counter()
        try:
            r = await self._post("/api/embed", {"model": model, "input": texts})
            if r.status_code != 200:
                # legacy endpoint
                r2 = await self._post(
                    "/api/embeddings", {"model": model, "prompt": texts[0]}
                )
                if r2.status_code != 200:
                    return None
                ms = (time.perf_counter() - t0) * 1000
                self.latency.record("embed", ms)
                return [r2.json().get("embedding", [])]
            data = r.json()
            embeddings = data.get("embeddings") or []
            ms = (time.perf_counter() - t0) * 1000
            self.latency.record("embed", ms)
            return embeddings
        except Exception:
            return None