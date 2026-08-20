"""Typed application configuration loaded from environment variables."""

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    app_version: str = Field(default="0.2.0", validation_alias="APP_VERSION")
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
