"""Runtime configuration, read from environment variables prefixed ``FCRAG_`` and ``.env``."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
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

    llm_model: str = "anthropic/claude-sonnet-5-5"
    local_llm_model: str = "ollama/qwen3:14b"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    restricted_mode: bool = False
    """When true, every LLM and embedding call goes to local models only."""

    @property
    def active_llm_model(self) -> str:
        return self.local_llm_model if self.restricted_mode else self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
