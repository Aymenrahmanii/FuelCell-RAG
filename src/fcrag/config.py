"""Runtime configuration, read from environment variables prefixed ``FCRAG_`` and ``.env``."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FCRAG_", env_file=".env", extra="ignore")

    env: Literal["dev", "ci", "prod"] = "dev"

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "fuelcell_chunks"
    postgres_dsn: SecretStr = SecretStr("postgresql+psycopg://fcrag:fcrag@localhost:5432/fcrag")
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "fcrag"
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "fcrag-raw"
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FCRAG_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FCRAG_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY"),
    )

    llm_model: str = "groq/openai/gpt-oss-120b"
    llm_fallbacks: list[str] = ["gemini/gemini-3.5-flash"]
    """Tried in order when the main model fails (rate limit, outage). LiteLLM model strings."""
    local_llm_model: str = "ollama/qwen3:4b"
    llm_timeout_s: float = 60.0
    embedding_model: str = "BAAI/bge-m3"
    embedding_batch_size: int = 32
    embedding_max_tokens: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    restricted_mode: bool = False
    """When true, every LLM and embedding call goes to local models only."""

    # Ingestion
    systems_dir: Path = Path("data_gen/systems")
    synonyms_path: Path = Path("data_gen/synonyms.yaml")
    source_dirs: list[Path] = [Path("data/raw"), Path("data/generated")]
    sources_manifest: Path = Path("data/sources.yaml")
    element_cache_dir: Path | None = Path("data/processed/elements")
    """Parsed elements cached by file hash; None disables the cache."""
    pdf_table_mode: Literal["accurate", "fast"] = "accurate"
    pdf_ocr: bool = False
    """OCR in Docling. All public PDFs have a text layer; enable for scanned documents."""
    drawing_vlm: bool = False
    """Add a vision model's description of each drawing sheet (marked low confidence)."""
    vlm_model: str = "gemini/gemini-3.5-flash"
    local_vlm_model: str | None = None
    """Vision model for restricted mode, e.g. ``ollama/qwen2.5vl:7b``; None skips the step."""
    max_attempts: int = 3
    chunk_strategy: Literal["section", "fixed"] = "section"
    chunk_max_tokens: int = 800
    chunk_min_tokens: int = 80
    chunk_fixed_tokens: int = 512
    chunk_overlap_tokens: int = 64
    contextual_headers: bool = True

    # Retrieval and generation
    prompts_dir: Path = Path("prompts")
    eval_runs_dir: Path = Path("eval/runs")
    """Saved evaluation runs, shown by the dashboard (GET /eval/runs)."""
    golden_path: Path = Path("eval/golden_set.jsonl")
    prefetch_limit: int = 50
    rerank_top_k: int = 8
    response_cache_ttl_s: int = 86_400
    """How long a computed answer is replayed for the same question; 0 turns the cache off.
    Any ingestion changes the cache key, so answers never outlive the documents they cite."""
    audit_retention_days: int = 90
    """Days an answered question (user, groups, sources, answer) stays in the audit log;
    ``fcrag audit-prune`` removes older rows. 0 turns the audit log off."""
    rerank_threshold: float = 0.21
    """Minimum reranker score (0..1) to count as evidence; if none passes, answer 'not found'.
    Calibrated on the golden set (2026-10-25): answerable questions scored >= 0.228, six of
    seven unanswerable ones <= 0.201. Recheck with ``fcrag eval`` when the set grows."""

    # API and UI
    api_key: SecretStr | None = None
    """When set, every API request needs a matching ``X-API-Key`` header."""
    api_url: str = "http://127.0.0.1:8000"
    """Where the Streamlit UI finds the API."""

    @property
    def active_llm_model(self) -> str:
        return self.local_llm_model if self.restricted_mode else self.llm_model


@lru_cache
def get_settings() -> Settings:
    # Provider SDKs (LiteLLM: GROQ_API_KEY, GEMINI_API_KEY, ...) read os.environ, not Settings.
    # Variables already set, e.g. by Docker, take precedence over the file.
    load_dotenv(".env", override=False)
    return Settings()
