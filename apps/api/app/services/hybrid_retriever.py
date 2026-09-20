"""Hybrid retrieval — keyword + vector + graph + document lookup, merged
with Reciprocal Rank Fusion (RRF) and returned as ordered evidence.

Mirrors README section 11: parallel retrieval then merge + rank.
"""
from __future__ import annotations

import json
import re

from sqlmodel import Session, select

from app.services.embeddings import EmbeddingProvider, cosine_similarity
from app.services.graph_memory import GraphMemory
from app.models import Chunk, Document, Entity

_TAG_RE = re.compile(r"\b([A-Z]{1,6}[- _]?\d{2,4}[A-Z0-9]?)\b")

RRF_K = 60


class HybridRetriever:
    def __init__(self, settings, graph: GraphMemory, embeddings: EmbeddingProvider):
        self.settings = settings
        self.graph = graph
        self.embeddings = embeddings

    # ── exact tag / keyword search ────────────────────────────
    def keyword_search(self, session: Session, project_id: int, query: str, top_k: int = 8):
        results = []
        tags_in_query = set()
        for m in _TAG_RE.findall(query.upper()):
            tags_in_query.add(re.sub(r"[ _]", "-", m))
        if tags_in_query:
            rows = session.exec(
                select(Entity).where(
                    Entity.project_id == project_id,
                    Entity.canonical_tag.in_(list(tags_in_query)),
                )
            ).all()
            for e in rows:
                results.append(
                    {
                        "source": "entity",
                        "entity_id": e.id,
                        "tag": e.canonical_tag,
                        "text": f"{e.label or e.canonical_tag}",
                        "page_id": e.page_id,
                        "bbox": [e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
                        "confidence": e.confidence,
                        "score": e.confidence,
                    }
                )
        keywords = query.lower().split()
        for kw in keywords[:4]:
            if len(kw) < 2:
                continue
            like = f"%{kw}%"
            rows = session.exec(
                select(Entity).where(
                    Entity.project_id == project_id,
                    (Entity.canonical_tag.ilike(like)) | (Entity.label.ilike(like)),
                ).limit(top_k)
            ).all()
            for e in rows:
                results.append(
                    {
                        "source": "entity",
                        "entity_id": e.id,
                        "tag": e.canonical_tag,
                        "text": f"{e.label or e.canonical_tag}",
                        "page_id": e.page_id,
                        "bbox": [e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
                        "confidence": e.confidence,
                        "score": e.confidence * 0.8,
                    }
                )
        return results

    # ── graph traversal ───────────────────────────────────────
    def graph_search(self, query: str, top_k: int = 12):
        from app.services.entity_normalizer import normalize_tag

        results = []
        tags_in_query = set()
        for m in _TAG_RE.findall(query.upper()):
            tags_in_query.add(normalize_tag(m))
        if not tags_in_query:
            return results
        for tag in tags_in_query:
            if tag not in self.graph.graph:
                continue
            for nb in self.graph.neighbors(tag):
                results.append(
                    {
                        "source": "graph",
                        "tag": nb["tag"],
                        "relation": nb["relation"],
                        "from": tag,
                        "text": f"{tag} {nb['relation']} {nb['tag']}",
                        "confidence": 0.9,
                        "score": 1.0,
                    }
                )
            for up in self.graph.upstream(tag):
                # An upstream edge runs `up -> tag`: the neighbour is the
                # SOURCE and the queried node is the target. Recording both
                # fields as the neighbour produced a self-loop that matched no
                # stored relationship, so these edges lost their provenance and
                # rendered as "L-101 -> TO -> L-101" in the evidence panel.
                results.append(
                    {
                        "source": "graph",
                        "tag": tag,
                        "relation": up["relation"],
                        "from": up["tag"],
                        "text": f"{up['tag']} {up['relation']} {tag}",
                        "confidence": 0.9,
                        "score": 0.9,
                    }
                )
        return results[:top_k]
# ── vector semantic search ────────────────────────────────
    async def vector_search(self, session: Session, project_id: int, query: str, top_k: int = 6):
        query_vec = await self.embeddings.embed_query(query)
        rows = session.exec(
            select(Chunk).where(Chunk.project_id == project_id).limit(400)
        ).all()
        scored = []
        for c in rows:
            emb = c.embedding_json
            if not emb:
                continue
            try:
                vec = json.loads(emb)
            except (ValueError, TypeError):
                continue
            if not vec or len(vec) != len(query_vec):
                continue
            sim = cosine_similarity(query_vec, vec)
            if sim > 0.05:
                scored.append((sim, c))
        scored.sort(key=lambda t: t[0], reverse=True)
        out = []
        for sim, c in scored[:top_k]:
            out.append(
                {
                    "source": "chunk",
                    "chunk_id": c.id,
                    "page_id": c.page_id,
                    "text": c.text[:400],
                    "bbox": json.loads(c.bbox_json or "[]"),
                    "confidence": max(0.5, float(sim)),
                    "score": float(sim),
                }
            )
        return out

    # ── document / source lookup ──────────────────────────────
    def document_lookup(self, session: Session, project_id: int, query: str, top_k: int = 5):
        results = []
        docs = session.exec(
            select(Document).where(Document.project_id == project_id).limit(20)
        ).all()
        ql = query.lower()
        for d in docs:
            if any(k in d.name.lower() for k in ("document", "manual", "report", "pdf")):
                results.append(
                    {
                        "source": "document",
                        "document_id": d.id,
                        "tag": d.name,
                        "text": f"document {d.name} ({d.status})",
                        "confidence": 0.6,
                        "score": 0.3 if ql in d.name.lower() else 0.2,
                    }
                )
        return results[:top_k]

    # ── merge + rank (RRF) ────────────────────────────────────
    @staticmethod
    def _rrf_rank(lists_of_results: list[list[dict]], top_k: int):
        scores: dict[int, float] = {}
        items: dict[int, dict] = {}
        for result_list in lists_of_results:
            for rank, item in enumerate(result_list[:40]):
                key = hash(json.dumps(item, sort_keys=True, default=str))
                if key not in items:
                    items[key] = item
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
        # items.items() yields (key, item_dict) — unpacking the dict as the
        # score wrote the whole item into `score` on every result.
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [
            dict(items[key], rank=i + 1, score=round(score, 6))
            for i, (key, score) in enumerate(ranked[:top_k])
        ]

    async def retrieve(
        self, session: Session, project_id: int, query: str, top_k: int = 10
    ) -> list[dict]:
        kw = self.keyword_search(session, project_id, query, top_k=max(6, top_k))
        gr = self.graph_search(query, top_k=max(8, top_k))
        vec = await self.vector_search(session, project_id, query, top_k=max(4, top_k))
        doc = self.document_lookup(session, project_id, query, top_k=4)
        return self._rrf_rank([kw, gr, vec, doc], top_k)