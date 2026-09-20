"""SQLModel ORM models — the boring inspectable core data model.

Mirrors README section 8: documents, document_pages, entities,
relationships, chunks, memories, plus projects/conversations/audit.
JSON-flavoured columns are stored as TEXT to keep SQLite inspectable.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from app.db import utcnow


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="projects.id")
    name: str
    mime_type: str = ""
    path: str = ""
    sha256: str = ""
    status: str = Field(default="uploaded")  # uploaded|processing|ready|failed
    stage: str = ""                          # current pipeline stage label
    page_count: int = 0
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class DocumentPage(SQLModel, table=True):
    __tablename__ = "document_pages"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: int = Field(index=True, foreign_key="documents.id")
    page_number: int
    image_path: str = ""
    width: int = 0
    height: int = 0
    text: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Entity(SQLModel, table=True):
    __tablename__ = "entities"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="projects.id")
    page_id: int = Field(index=True, foreign_key="document_pages.id")
    document_id: int = Field(index=True, foreign_key="documents.id")
    entity_type: str = ""
    canonical_tag: str = Field(index=True)
    label: str = ""
    raw_text: str = ""
    confidence: float = 0.0
    bbox_x: float = 0.0
    bbox_y: float = 0.0
    bbox_w: float = 0.0
    bbox_h: float = 0.0
    metadata_json: str = Field(default="{}", sa_column=Column(Text))


class Relationship(SQLModel, table=True):
    __tablename__ = "relationships"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="projects.id")
    document_id: int = Field(foreign_key="documents.id", default=0)
    source_entity_id: int = Field(default=0)
    target_entity_id: int = Field(default=0)
    source_tag: str = Field(index=True)
    target_tag: str = Field(index=True)
    relationship_type: str = Field(index=True)
    confidence: float = 0.0
    source_page_id: int = Field(default=0)
    metadata_json: str = Field(default="{}", sa_column=Column(Text))


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True)
    document_id: int = Field(index=True)
    page_id: int = 0
    text: str = ""
    bbox_json: str = Field(default="[]", sa_column=Column(Text))
    embedding_json: str = Field(default="[]", sa_column=Column(Text))
    embedding_id: str = ""
    metadata_json: str = Field(default="{}", sa_column=Column(Text))


class Memory(SQLModel, table=True):
    __tablename__ = "memories"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="projects.id")
    memory_type: str = ""
    summary: str = ""
    importance: float = 0.5
    source_entity_ids: str = Field(default="[]", sa_column=Column(Text))
    source_document_ids: str = Field(default="[]", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(index=True, foreign_key="projects.id")
    title: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversations.id")
    role: str = ""
    content: str = ""
    confidence: Optional[float] = None
    claims_json: str = Field(default="[]", sa_column=Column(Text))
    sources_json: str = Field(default="[]", sa_column=Column(Text))
    # Artefacts produced by this turn. Stored on the message so reopening a
    # conversation brings its files back with it, the way the evidence does —
    # a deliverable that only exists in the live stream is lost on reload.
    artifacts_json: str = Field(default="[]", sa_column=Column(Text))
    # "chat" | "agent": which path produced the turn, so the UI can replay the
    # right affordances instead of guessing from the content.
    kind: str = Field(default="chat")
    created_at: datetime = Field(default_factory=utcnow)


class AuditEvent(SQLModel, table=True):
    """One audit entry, hash-chained to the one before it (README §4.11).

    `prev_hash` + `entry_hash` make the log tamper-evident: altering entry 400
    changes its hash, which no longer matches entry 401's `prev_hash`, so the
    break is detectable and localised rather than invisible.
    """

    __tablename__ = "audit_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    time: datetime = Field(default_factory=utcnow)
    session_id: str = ""
    user_action: str = ""
    model: str = ""
    model_version: str = ""
    retrieval_count: int = 0
    tool_name: str = ""
    result_status: str = ""
    seq: int = Field(default=0, index=True)
    prev_hash: str = ""
    entry_hash: str = ""



