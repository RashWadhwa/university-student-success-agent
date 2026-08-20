"""Shared pytest fixtures."""

from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import Environment, LLMProviderName, Settings
from backend.database.manager import DatabaseReadiness
from backend.main import create_app


class ReadyDatabaseManager:
    """No-network database lifecycle double for the normal unit suite."""

    async def check_readiness(self) -> DatabaseReadiness:
        return DatabaseReadiness(database=True, pgvector=True)

    @asynccontextmanager
    async def session(self) -> Any:
        raise AssertionError("A unit test must inject an indexing/retrieval service")
        yield

    async def close(self) -> None:
        return None


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
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
        document_storage_path=tmp_path / "documents",
        embedding_dimensions=8,
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    return create_app(test_settings, database_manager=ReadyDatabaseManager())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
