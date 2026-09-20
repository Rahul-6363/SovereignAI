"""Pydantic API schemas for the Meshcore backend."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Projects ──────────────────────────────────────────────────
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class ProjectStats(BaseModel):
    documents: int = 0
    entities: int = 0
    relationships: int = 0
    memories: int = 0
    chunks: int = 0
    last_indexed_at: Optional[datetime] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str = ""
    created_at: datetime
    stats: ProjectStats = ProjectStats()


# ── Documents / pages ─────────────────────────────────────────
class DocumentOut(BaseModel):
    id: int
    project_id: int
    name: str
    mime_type: str
    sha256: str
    status: str
    stage: str
    page_count: int
    error: str
    created_at: datetime


class PageOut(BaseModel):
    id: int
    document_id: int
    page_number: int
    image_url: str
    width: int
    height: int


class IngestionStatusOut(BaseModel):
    document_id: int
    status: str
    stage: str
    progress: float = 0.0  # 0..1
    pages: int = 0
    entities: int = 0
    relationships: int = 0
    chunks: int = 0
    error: str = ""


# ── Entities / relationships ──────────────────────────────────
class EntityOut(BaseModel):
    id: int
    page_id: int
    entity_type: str
    canonical_tag: str
    label: str = ""
    raw_text: str = ""
    confidence: float = 0.0
    bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationshipOut(BaseModel):
    id: int
    source_tag: str
    target_tag: str
    relationship_type: str
    confidence: float = 0.0
    page_id: int = 0


class EntityDetailOut(BaseModel):
    entity: EntityOut
    connections: list[RelationshipOut] = Field(default_factory=list)
    source_document: str = ""
    page_number: int = 0
    image_url: str = ""


# ── Graph ─────────────────────────────────────────────────────
class GraphNodeOut(BaseModel):
    id: str
    tag: str
    type: str
    label: str
    confidence: float
    page_id: Optional[int] = None
    bbox: Optional[list[float]] = None


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    relation: str
    confidence: float


class MemoryGraphOut(BaseModel):
    nodes: list[GraphNodeOut] = Field(default_factory=list)
    edges: list[GraphEdgeOut] = Field(default_factory=list)
    project_id: int


# ── Memory / summaries ────────────────────────────────────────
class MemoryOut(BaseModel):
    id: int
    memory_type: str
    summary: str
    importance: float


# ── Retrieval / evidence ──────────────────────────────────────
class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)


class EvidenceSource(BaseModel):
    source_type: str  # graph | pid | document | chunk | memory
    entity: Optional[str] = None
    relation: Optional[str] = None
    target: Optional[str] = None
    document: Optional[str] = None
    document_id: Optional[int] = None
    entity_id: Optional[int] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None
    text: Optional[str] = None
    confidence: Optional[float] = None


class EvidencePacket(BaseModel):
    answer_context: list[EvidenceSource] = Field(default_factory=list)
    confidence: float = 0.0
    query_intent: str = "PLANT_MEMORY"
    retrieved_from: str = ""


class SearchResultItem(BaseModel):
    rank: int
    source_type: str
    tag: Optional[str] = None
    text: Optional[str] = None
    document: Optional[str] = None
    page: Optional[int] = None
    bbox: Optional[list[float]] = None
    score: float = 0.0
    confidence: float = 0.0


class SearchResponse(BaseModel):
    query: str
    intent: str
    results: list[SearchResultItem] = Field(default_factory=list)
    evidence: EvidencePacket


# ── Chat ──────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[int] = None
    retrieval_top_k: int = Field(default=10, ge=1, le=30)
    # plant | general | code | think. Unknown values fall back to plant
    # in `normalize_mode` rather than 422-ing a chat turn.
    mode: str = "plant"


class ClaimOut(BaseModel):
    text: str
    confidence: float
    evidence_ids: list[str] = Field(default_factory=list)


class SourceOut(BaseModel):
    document: str
    page: int = 0
    bbox: Optional[list[float]] = None
    source_type: str = "pid"


class ChatResponseShape(BaseModel):
    message: str
    confidence: float
    claims: list[ClaimOut] = Field(default_factory=list)
    sources: list[SourceOut] = Field(default_factory=list)


class ConversationOut(BaseModel):
    id: int
    project_id: int
    title: str
    created_at: datetime
    updated_at: datetime
    # Enough to render a chat rail without a second round trip per row.
    message_count: int = 0
    preview: str = ""


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", max_length=120)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    confidence: Optional[float] = None
    created_at: datetime
    kind: str = "chat"
    sources: list[dict] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)


# ── Trust / audit ─────────────────────────────────────────────
class ModelStatusOut(BaseModel):
    name: str
    installed: bool
    size: str = ""
    role: str


class TrustStatusOut(BaseModel):
    ollama_connected: bool
    external_llm_calls: int = 0
    network_egress: str = "Blocked"
    documents_local: bool = True
    audit_logging: bool = True
    models: list[ModelStatusOut] = Field(default_factory=list)
    active_model: str = ""


class AuditEventOut(BaseModel):
    id: int
    time: datetime
    session_id: str
    user_action: str
    model: str
    model_version: str
    retrieval_count: int
    tool_name: str
    result_status: str
    seq: int = 0
    entry_hash: str = ""
    prev_hash: str = ""