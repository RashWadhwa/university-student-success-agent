"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

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


class EvaluationProviderName(StrEnum):
    """Independent evaluation providers supported by Stage 7."""

    GEMINI = "gemini"
    MOCK = "mock"


class AuthMode(StrEnum):
    """Supported authentication boundaries."""

    LOCAL = "local"
    SUPABASE = "supabase"


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
    app_version: str = Field(default="0.8.0", validation_alias="APP_VERSION")
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
    auth_mode: AuthMode = Field(default=AuthMode.LOCAL, validation_alias="AUTH_MODE")
    supabase_auth_url: str | None = Field(default=None, validation_alias="SUPABASE_AUTH_URL")
    supabase_jwt_audience: str = Field(
        default="authenticated", validation_alias="SUPABASE_JWT_AUDIENCE", min_length=1
    )
    auth_jwks_cache_seconds: int = Field(
        default=600, validation_alias="AUTH_JWKS_CACHE_SECONDS", ge=30, le=1200
    )
    local_auth_role: Literal["student", "staff", "admin"] = Field(
        default="admin", validation_alias="LOCAL_AUTH_ROLE"
    )
    default_tenant_id: str = Field(
        default="default",
        validation_alias="DEFAULT_TENANT_ID",
        pattern=r"^[A-Za-z0-9._:-]{1,100}$",
    )
    request_body_max_bytes: int = Field(
        default=12 * 1024 * 1024,
        validation_alias="REQUEST_BODY_MAX_BYTES",
        ge=1024,
        le=110 * 1024 * 1024,
    )
    rate_limit_secret: SecretStr | None = Field(default=None, validation_alias="RATE_LIMIT_SECRET")
    rate_limit_window_seconds: int = Field(
        default=60, validation_alias="RATE_LIMIT_WINDOW_SECONDS", ge=10, le=3600
    )
    rate_limit_ask: int = Field(default=20, validation_alias="RATE_LIMIT_ASK", ge=1, le=1000)
    rate_limit_documents: int = Field(
        default=10, validation_alias="RATE_LIMIT_DOCUMENTS", ge=1, le=1000
    )
    rate_limit_retrieval: int = Field(
        default=30, validation_alias="RATE_LIMIT_RETRIEVAL", ge=1, le=1000
    )
    rate_limit_evaluation: int = Field(
        default=2, validation_alias="RATE_LIMIT_EVALUATION", ge=1, le=100
    )
    rate_limit_memory: int = Field(default=20, validation_alias="RATE_LIMIT_MEMORY", ge=1, le=1000)
    memory_max_fact_chars: int = Field(
        default=1000, validation_alias="MEMORY_MAX_FACT_CHARS", ge=50, le=2000
    )
    memory_preference_retention_days: int = Field(
        default=365, validation_alias="MEMORY_PREFERENCE_RETENTION_DAYS", ge=1, le=730
    )
    memory_case_retention_days: int = Field(
        default=90, validation_alias="MEMORY_CASE_RETENTION_DAYS", ge=1, le=365
    )
    audit_retention_days: int = Field(
        default=180, validation_alias="AUDIT_RETENTION_DAYS", ge=30, le=730
    )
    primary_institution_name: str = Field(
        default="Harper Adams University",
        validation_alias="PRIMARY_INSTITUTION_NAME",
        min_length=1,
        max_length=255,
    )
    primary_institution_corpus_manifest: Path = Field(
        default=Path("data/institutions/primary-corpus.json"),
        validation_alias="PRIMARY_INSTITUTION_CORPUS_MANIFEST",
    )
    primary_institution_source_hosts: list[str] = Field(
        default_factory=lambda: [
            "www.harper-adams.ac.uk",
            "cdn.harper-adams.ac.uk",
        ],
        validation_alias="PRIMARY_INSTITUTION_SOURCE_HOSTS",
        min_length=1,
        max_length=20,
    )
    corpus_download_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="CORPUS_DOWNLOAD_TIMEOUT_SECONDS",
        gt=0,
        le=120,
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
    eval_provider: EvaluationProviderName = Field(
        default=EvaluationProviderName.GEMINI,
        validation_alias="EVAL_PROVIDER",
    )
    eval_model: str = Field(
        default="gemini-3.1-flash-lite",
        validation_alias="EVAL_MODEL",
        min_length=1,
        max_length=200,
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
    )
    eval_max_cases_per_run: int = Field(
        default=50,
        validation_alias="EVAL_MAX_CASES_PER_RUN",
        ge=1,
        le=100,
    )
    eval_max_judge_calls: int = Field(
        default=100,
        validation_alias="EVAL_MAX_JUDGE_CALLS",
        ge=0,
        le=200,
    )
    eval_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="EVAL_TIMEOUT_SECONDS",
        gt=0,
        le=300,
    )
    evaluation_dataset_path: Path = Field(
        default=Path("data/evaluation/stage7-policy-cases.jsonl"),
        validation_alias="EVALUATION_DATASET_PATH",
    )
    langfuse_enabled: bool = Field(default=False, validation_alias="LANGFUSE_ENABLED")
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias="LANGFUSE_HOST",
        min_length=1,
        max_length=2048,
    )
    langfuse_public_key: SecretStr | None = Field(
        default=None,
        validation_alias="LANGFUSE_PUBLIC_KEY",
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias="LANGFUSE_SECRET_KEY",
    )
    langfuse_event_timeout_seconds: float = Field(
        default=0.5,
        validation_alias="LANGFUSE_EVENT_TIMEOUT_SECONDS",
        ge=0.05,
        le=5.0,
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

    @field_validator("primary_institution_name")
    @classmethod
    def normalise_primary_institution_name(cls, value: str) -> str:
        """Store one bounded display/filter value for the configured institution."""

        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("PRIMARY_INSTITUTION_NAME must not be blank")
        return cleaned

    @field_validator("primary_institution_source_hosts")
    @classmethod
    def validate_primary_institution_source_hosts(cls, values: list[str]) -> list[str]:
        """Accept hostnames only so corpus loading cannot be configured with URL credentials."""

        hosts: list[str] = []
        for value in values:
            host = value.strip().rstrip(".").casefold()
            if (
                not host
                or "://" in host
                or "/" in host
                or "@" in host
                or ":" in host
                or "." not in host
                or host.endswith((".local", ".internal", ".localhost"))
                or any(character.isspace() for character in host)
            ):
                raise ValueError("PRIMARY_INSTITUTION_SOURCE_HOSTS must contain hostnames only")
            try:
                ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("PRIMARY_INSTITUTION_SOURCE_HOSTS must not contain IP addresses")
            if host not in hosts:
                hosts.append(host)
        return hosts

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

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: list[str]) -> list[str]:
        origins: list[str] = []
        for value in values:
            candidate = value.strip().rstrip("/")
            parsed = urlsplit(candidate)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS_ORIGINS must contain credential-free HTTP(S) origins")
            if candidate not in origins:
                origins.append(candidate)
        return origins

    @field_validator("supabase_auth_url")
    @classmethod
    def validate_supabase_auth_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        candidate = value.strip().rstrip("/")
        parsed = urlsplit(candidate)
        is_local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        if (
            (parsed.scheme != "https" and not is_local_http)
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.endswith("/auth/v1")
        ):
            raise ValueError(
                "SUPABASE_AUTH_URL must be a credential-free /auth/v1 URL; "
                "HTTP is allowed only for localhost"
            )
        return candidate

    @field_validator(
        "openai_api_key",
        "openai_organization",
        "openai_project",
        "openai_base_url",
        "gemini_api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "supabase_auth_url",
        "rate_limit_secret",
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
        if self.langfuse_enabled:
            if self.langfuse_public_key is None or self.langfuse_secret_key is None:
                raise ValueError("Langfuse keys are required when LANGFUSE_ENABLED is true")
            if self.langfuse_host.rstrip("/") != "https://cloud.langfuse.com":
                raise ValueError("LANGFUSE_HOST must use the Langfuse Cloud EU endpoint")
        if self.environment in {Environment.STAGING, Environment.PRODUCTION}:
            if self.auth_mode is not AuthMode.SUPABASE:
                raise ValueError("AUTH_MODE must be supabase outside local/test environments")
            if self.supabase_auth_url is None:
                raise ValueError("SUPABASE_AUTH_URL is required outside local/test environments")
            if self.rate_limit_secret is None:
                raise ValueError("RATE_LIMIT_SECRET is required outside local/test environments")
        if self.is_production:
            if not self.cors_origins:
                raise ValueError("CORS_ORIGINS must explicitly allow the production frontend")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS cannot contain '*' in production")
            if any(urlsplit(origin).scheme != "https" for origin in self.cors_origins):
                raise ValueError("CORS_ORIGINS must use HTTPS in production")
            if self.supabase_auth_url and urlsplit(self.supabase_auth_url).scheme != "https":
                raise ValueError("SUPABASE_AUTH_URL must use HTTPS in production")
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
