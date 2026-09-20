"""SQLite database bootstrap (SQLModel / SQLAlchemy)."""
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_settings = get_settings()
_settings.ensure_dirs()
_settings.database_path.parent.mkdir(parents=True, exist_ok=True)


def _engine_url() -> str:
    db_path: Path = _settings.database_path
    # use forward slashes; add check_same_thread=False for FastAPI threading
    return f"sqlite:///{db_path.as_posix()}?check_same_thread=False"


engine = create_engine(
    _engine_url(),
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)


# Columns added after a table first shipped. SQLModel's create_all only
# creates missing TABLES, never missing COLUMNS, so an existing development
# database silently keeps the old shape and every insert fails. SQLite
# supports ADD COLUMN, which is all these need.
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "audit_events": [
        ("seq", "INTEGER DEFAULT 0"),
        ("prev_hash", "VARCHAR DEFAULT ''"),
        ("entry_hash", "VARCHAR DEFAULT ''"),
    ],
    "messages": [
        ("artifacts_json", "TEXT DEFAULT '[]'"),
        ("kind", "VARCHAR DEFAULT 'chat'"),
    ],
}


def _apply_column_migrations() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    """Create all tables, then add any columns an older database is missing."""
    # Import models so SQLModel registers them.
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _apply_column_migrations()


def get_session():
    with Session(engine) as session:
        yield session