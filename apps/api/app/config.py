"""Application configuration.

All model names and routing switches live here in ONE place so that
model selection is configuration, not application logic.
"""
import sys
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/app/config.py -> repo root is 3 levels up
REPO_ROOT = Path(__file__).resolve().parents[3]

# allow `from packages.prompts import ...` regardless of cwd
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Meshcore API"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Ollama gateway
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:4b"
    ollama_vision_model: str = "qwen2.5vl:3b"
    ollama_embed_model: str = "nomic-embed-text"
    vision_fallback_model: str = "qwen2.5vl:7b"
    reasoning_fallback_model: str = "qwen3:8b"
    # Generation caps (CPU-friendly): bounded answers + bounded vision JSON
    ollama_num_predict: int = 320
    vision_num_predict: int = 1024

    # Storage
    database_url: str = "sqlite:///./data/plant_memory.db"
    upload_dir: str = "./data/uploads"
    page_dir: str = "./data/pages"
    index_dir: str = "./data/indexes"
    demo_dir: str = "./data/demo"
    deliverable_dir: str = "./data/deliverables"

    # Trust / routing
    enable_model_escalation: bool = False
    enable_audit_log: bool = True
    enable_external_network: bool = False
    force_offline_extraction: bool = False

    # Vector embeddings dimensions (deterministic fallback implementation)
    embed_dim: int = 384

    # ── P&ID pipeline (README §4.5) ──
    # Tiling trades vision-model calls for resolution. "auto" scales the grid
    # with sheet size; "off" keeps the single-pass path; "3x2" forces a grid.
    pid_tile_grid: str = "auto"
    pid_max_tiles: int = 9
    # Prefer a born-digital PDF's own text layer over re-reading a render.
    pid_use_vector_layer: bool = True
    # OCR a raster sheet before falling back to the vision model. A P&ID is
    # mostly text; OCR reads it in seconds where the VLM needs minutes.
    pid_use_ocr: bool = True
    # Below this many entities the next (costlier) layer is allowed to run.
    pid_min_entities: int = 8

    @property
    def upload_path(self) -> Path:
        return _resolve(self.upload_dir)

    @property
    def page_path(self) -> Path:
        return _resolve(self.page_dir)

    @property
    def index_path(self) -> Path:
        return _resolve(self.index_dir)

    @property
    def demo_path(self) -> Path:
        return _resolve(self.demo_dir)

    @property
    def deliverable_path(self) -> Path:
        return _resolve(self.deliverable_dir)

    @property
    def database_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite:///"):
            rel = url.removeprefix("sqlite:///")
            rel = rel.replace("\\", "/")
            return _resolve(rel)
        return Path(url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        for p in (
            self.upload_path, self.page_path, self.index_path,
            self.demo_path, self.deliverable_path,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s