"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Supported application environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProviderName(StrEnum):
    """Language-model providers supported by the current build."""

    OPENAI = "openai"
    MOCK = "mock"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = Field(
        default="University Student Success Agent",
        validation_alias="APP_NAME",
    )
    app_version: str = Field(default="0.6.0", validation_alias="APP_VERSION")
    environment: Environment = Field(
        default=Environment.DEVELOPMENT,
        validation_alias="ENVIRONMENT",
    )
    debug: bool = Field(default=False, validation_alias="DEBUG")
    docs_enabled: bool = Field(default=True, validation_alias="DOCS_ENABLED")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        validation_alias="LOG_LEVEL",
    )
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8501",
        ],
        validation_alias="CORS_ORIGINS",
    )

    llm_provider: LLMProviderName = Field(
        default=LLMProviderName.OPENAI,
        validation_alias="LLM_PROVIDER",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    openai_model: str = Field(
        default="gpt-5-mini",
        validation_alias="OPENAI_MODEL",
        min_length=1,
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="OPENAI_EMBEDDING_MODEL",
        min_length=1,
    )
    openai_organization: str | None = Field(
        default=None,
        validation_alias="OPENAI_ORG_ID",
    )
    openai_project: str | None = Field(
        default=None,
        validation_alias="OPENAI_PROJECT_ID",
    )
    openai_base_url: str | None = Field(
        default=None,
        validation_alias="OPENAI_BASE_URL",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="LLM_TIMEOUT_SECONDS",
        gt=0,
        le=600,
    )
    llm_connect_timeout_seconds: float = Field(
        default=5.0,
        validation_alias="LLM_CONNECT_TIMEOUT_SECONDS",
        gt=0,
        le=60,
    )
    llm_max_retries: int = Field(
        default=2,
        validation_alias="LLM_MAX_RETRIES",
        ge=0,
        le=10,
    )
    llm_max_output_tokens: int = Field(
        default=1200,
        validation_alias="LLM_MAX_OUTPUT_TOKENS",
        ge=64,
        le=100_000,
    )
    enable_llm_smoke_test: bool = Field(
        default=True,
        validation_alias="ENABLE_LLM_SMOKE_TEST",
    )
    document_storage_path: Path = Field(
        default=Path("data/documents"),
        validation_alias="DOCUMENT_STORAGE_PATH",
    )
    max_document_size_bytes: int = Field(
        default=10 * 1024 * 1024,
        validation_alias="MAX_DOCUMENT_SIZE_BYTES",
        ge=1024,
        le=100 * 1024 * 1024,
    )
    chunk_size: int = Field(
        default=1200,
        validation_alias="CHUNK_SIZE",
        ge=100,
        le=100_000,
    )
    chunk_overlap: int = Field(
        default=200,
        validation_alias="CHUNK_OVERLAP",
        ge=0,
        le=20_000,
    )
    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://student_success:student_success@localhost:5432/student_success"
        ),
        validation_alias="DATABASE_URL",
        min_length=1,
    )
    database_pool_size: int = Field(
        default=5,
        validation_alias="DATABASE_POOL_SIZE",
        ge=1,
        le=50,
    )
    database_max_overflow: int = Field(
        default=10,
        validation_alias="DATABASE_MAX_OVERFLOW",
        ge=0,
        le=100,
    )
    database_pool_timeout: float = Field(
        default=30.0,
        validation_alias="DATABASE_POOL_TIMEOUT",
        gt=0,
        le=300,
    )
    database_readiness_timeout: float = Field(
        default=3.0,
        validation_alias="DATABASE_READINESS_TIMEOUT",
        gt=0,
        le=30,
    )
    embedding_batch_size: int = Field(
        default=32,
        validation_alias="EMBEDDING_BATCH_SIZE",
        ge=1,
        le=2048,
    )
    embedding_dimensions: int = Field(
        default=1536,
        validation_alias="EMBEDDING_DIMENSIONS",
        ge=1,
        le=65_535,
    )
    ask_default_top_k: int = Field(
        default=5,
        validation_alias="ASK_DEFAULT_TOP_K",
        ge=1,
        le=100,
    )
    ask_max_top_k: int = Field(
        default=10,
        validation_alias="ASK_MAX_TOP_K",
        ge=1,
        le=100,
    )
    ask_min_evidence_count: int = Field(
        default=1,
        validation_alias="ASK_MIN_EVIDENCE_COUNT",
        ge=1,
        le=20,
    )
    ask_min_retrieval_score: float = Field(
        default=0.5,
        validation_alias="ASK_MIN_RETRIEVAL_SCORE",
        ge=0.0,
        le=1.0,
    )
    ask_max_evidence_chunks: int = Field(
        default=5,
        validation_alias="ASK_MAX_EVIDENCE_CHUNKS",
        ge=1,
        le=20,
    )
    ask_evidence_max_chars_per_chunk: int = Field(
        default=2000,
        validation_alias="ASK_EVIDENCE_MAX_CHARS_PER_CHUNK",
        ge=200,
        le=10_000,
    )
    ask_max_question_chars: int = Field(
        default=2000,
        validation_alias="ASK_MAX_QUESTION_CHARS",
        ge=100,
        le=10_000,
    )
    citation_excerpt_max_chars: int = Field(
        default=400,
        validation_alias="CITATION_EXCERPT_MAX_CHARS",
        ge=80,
        le=2000,
    )
    agent_max_tasks: int = Field(
        default=4,
        validation_alias="AGENT_MAX_TASKS",
        ge=1,
        le=10,
    )
    agent_max_tool_calls: int = Field(
        default=4,
        validation_alias="AGENT_MAX_TOOL_CALLS",
        ge=1,
        le=20,
    )
    agent_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="AGENT_TIMEOUT_SECONDS",
        gt=0,
        le=120,
    )
    agent_max_retries: int = Field(
        default=1,
        validation_alias="AGENT_MAX_RETRIES",
        ge=0,
        le=3,
    )
    agent_max_evidence_items: int = Field(
        default=5,
        validation_alias="AGENT_MAX_EVIDENCE_ITEMS",
        ge=1,
        le=20,
    )
    agent_max_provider_calls: int = Field(
        default=5,
        validation_alias="AGENT_MAX_PROVIDER_CALLS",
        ge=3,
        le=20,
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def normalise_log_level(cls, value: object) -> object:
        """Accept lower-case log levels while storing a canonical value."""

        return value.upper() if isinstance(value, str) else value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Ensure the API prefix has one leading slash and no trailing slash."""

        cleaned = value.strip()
        if not cleaned.startswith("/"):
            cleaned = f"/{cleaned}"
        if len(cleaned) > 1:
            cleaned = cleaned.rstrip("/")
        return cleaned

    @field_validator(
        "openai_api_key",
        "openai_organization",
        "openai_project",
        "openai_base_url",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        """Treat blank optional environment variables as unset."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_cross_field_configuration(self) -> "Settings":
        """Ensure chunking and ask limits form usable configurations."""

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        if self.ask_default_top_k > self.ask_max_top_k:
            raise ValueError("ASK_DEFAULT_TOP_K must not exceed ASK_MAX_TOP_K")
        if self.ask_min_evidence_count > self.ask_max_evidence_chunks:
            raise ValueError("ASK_MIN_EVIDENCE_COUNT must not exceed ASK_MAX_EVIDENCE_CHUNKS")
        if self.ask_min_evidence_count > self.agent_max_evidence_items:
            raise ValueError("ASK_MIN_EVIDENCE_COUNT must not exceed AGENT_MAX_EVIDENCE_ITEMS")
        return self

    @property
    def is_production(self) -> bool:
        """Return whether the application is running in production."""

        return self.environment is Environment.PRODUCTION

    @property
    def llm_smoke_test_enabled(self) -> bool:
        """Keep the diagnostic generation endpoint out of production."""

        return self.enable_llm_smoke_test and not self.is_production


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for the application process."""

    return Settings()
