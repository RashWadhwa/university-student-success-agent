"""Production security configuration fails closed."""

import pytest
from pydantic import ValidationError

from backend.core.config import AuthMode, Environment, Settings


def test_production_rejects_local_auth() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            auth_mode=AuthMode.LOCAL,
            cors_origins=["https://ui.example.edu"],
            rate_limit_secret="test-rate-key",
        )


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            auth_mode=AuthMode.SUPABASE,
            supabase_auth_url="https://project.supabase.co/auth/v1",
            cors_origins=["*"],
            rate_limit_secret="test-rate-key",
        )


def test_production_accepts_explicit_https_auth_and_origin() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        auth_mode=AuthMode.SUPABASE,
        supabase_auth_url="https://project.supabase.co/auth/v1/",
        cors_origins=["https://ui.example.edu/"],
        rate_limit_secret="test-rate-key",
    )
    assert settings.supabase_auth_url == "https://project.supabase.co/auth/v1"
    assert settings.cors_origins == ["https://ui.example.edu"]
