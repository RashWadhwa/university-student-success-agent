"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import Environment, LLMProviderName, Settings
from backend.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_name="Student Success Agent Test",
        app_version="0.1.0-test",
        environment=Environment.TESTING,
        debug=True,
        docs_enabled=True,
        log_level="CRITICAL",
        cors_origins=[],
        llm_provider=LLMProviderName.MOCK,
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
