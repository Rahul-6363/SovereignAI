"""Plant Memory Graph — NetworkX built from the SQLite records.

Persisted canonical entities/edges live in SQLite. The NetworkX graph is
rebuilt at app start (and after every ingest) for traversal and the UI.
"""
from __future__ import annotations

import json
from typing import Optional

import networkx as nx

from sqlmodel import Session, select

from app.config import Settings
from app.models import Entity, Relationship

# node/edge attribute keys
NODE_TAG = "tag"
NODE_TYPE = "type"
NODE_LABEL = "label"
EDGE_RELATION = "relation"


class GraphMemory:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.graph = nx.MultiDiGraph()

    # ── build from DB ─────────────────────────────────────────
    def rebuild(self, session: Session, project_id: int) -> nx.MultiDiGraph:
        self.graph = nx.MultiDiGraph()
        entities = session.exec(
            select(Entity).where(Entity.project_id == project_id)
        ).all()
        rels = session.exec(
            select(Relationship).where(Relationship.project_id == project_id)
        ).all()

        for e in entities:
            self.graph.add_node(
                e.canonical_tag,
                tag=e.canonical_tag,
                type=e.entity_type,
                label=e.label or e.canonical_tag,
                confidence=e.confidence,
                page_id=e.page_id,
                bbox=[e.bbox_x, e.bbox_y, e.bbox_w, e.bbox_h],
                _entity_id=e.id,
            )
        for r in rels:
            if self.graph.has_node(r.source_tag) and self.graph.has_node(r.target_tag):
                self.graph.add_edge(
                    r.source_tag,
                    r.target_tag,
                    relation=r.relationship_type,
                    confidence=r.confidence,
                    _rel_id=r.id,
                )
        return self.graph

    # ── queries ───────────────────────────────────────────────
    def entity(self, tag: str) -> Optional[dict]:
        node = self.graph.nodes.get(tag)
        if node is None:
            return None
        return dict(node)

    def neighbors(self, tag: str, relation: Optional[str] = None) -> list[dict]:
        if tag not in self.graph:
            return []
        out = []
        for _, tgt, data in self.graph.edges(tag, data=True):
            rel = data.get(EDGE_RELATION, "")
            if relation and rel != relation:
                continue
            node = self.graph.nodes.get(tgt, {})
            out.append({"tag": tgt, "relation": rel, "type": node.get("type", "")})
        return sorted(out, key=lambda x: (x["relation"], x["tag"]))

    def upstream(self, tag: str, relation: Optional[str] = None) -> list[dict]:
        if tag not in self.graph:
            return []
        out = []
        for src, _, data in self.graph.in_edges(tag, data=True):
            rel = data.get(EDGE_RELATION, "")
            if relation and rel != relation:
                continue
            node = self.graph.nodes.get(src, {})
            out.append({"tag": src, "relation": rel, "type": node.get("type", "")})
        return sorted(out, key=lambda x: (x["relation"], x["tag"]))

    def path(self, source: str, target: str, max_depth: int = 5) -> list[dict]:
        """One short path between two tags, as an edge list."""
        for path in nx.all_simple_paths(self.graph, source, target, cutoff=max_depth):
            steps = []
            for a, b in zip(path[:-1], path[1:]):
                data = self.graph.get_edge_data(a, b)
                rel = next(iter(data.values())).get(EDGE_RELATION, "CONNECTED_TO")
                steps.append({"from": a, "to": b, "relation": rel})
            return steps
        return []

    def instrument_edges(self, tag: str) -> list[dict]:
        return self.neighbors(tag, relation="HAS_INSTRUMENT")

    def summary(self) -> dict:
        return {"nodes": self.graph.number_of_nodes(), "edges": self.graph.number_of_edges()}

    def node_weights(self) -> dict:
        """Degree-based weights used by the UI graph layout."""
        degrees = dict(self.graph.degree())
        max_d = max(degrees.values()) if degrees else 1
        weights = {n: 1 + 2 * (d / max_d) for n, d in degrees.items()}
        return weights


def node_meta(node_id: str, node: dict) -> dict:
    return {k: node.get(k) for k in (NODE_TAG, NODE_TYPE, NODE_LABEL)}


def edge_meta(rel: Relationship) -> dict:
    return {
        "source": rel.source_tag,
        "relation": rel.relationship_type,
        "target": rel.target_tag,
        "confidence": rel.confidence,
    }


def to_graph_payload(graph: nx.MultiDiGraph, project_id: int) -> dict:
    nodes = []
    for tag, data in graph.nodes(data=True):
        nodes.append(
            {
                "id": tag,
                "tag": tag,
                "type": data.get("type", "tag"),
                "label": data.get("label", tag),
                "confidence": data.get("confidence", 0.5),
                "page_id": data.get("page_id"),
                "bbox": data.get("bbox"),
            }
        )
    edges = []
    seen = set()
    for a, b, data in graph.edges(data=True):
        key = (a, b, data.get("relation", ""))
        if key in seen:
            continue
        seen.add(key)
        edges.append(
            {
                "source": a,
                "target": b,
                "relation": data.get("relation", "CONNECTED_TO"),
                "confidence": data.get("confidence", 0.5),
            }
        )
    return {"project_id": project_id, "nodes": nodes, "edges": edges}