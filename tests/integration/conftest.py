"""PostgreSQL/pgvector fixtures, enabled only with TEST_DATABASE_URL."""

import os
from collections.abc import AsyncIterator, Iterator
from unittest.mock import patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from backend.database.manager import DatabaseManager


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        pytest.fail("TEST_DATABASE_URL must target a dedicated database containing 'test'")
    configuration = Config("alembic.ini")
    with patch.dict(os.environ, {"DATABASE_URL": database_url}):
        command.upgrade(configuration, "head")
        yield database_url


@pytest_asyncio.fixture
async def integration_database(
    migrated_database_url: str,
) -> AsyncIterator[DatabaseManager]:
    database = DatabaseManager(
        migrated_database_url,
        pool_size=2,
        max_overflow=1,
        pool_timeout=10,
    )
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE documents, semantic_memory, audit_logs, rate_limit_counters CASCADE"
            )
        )
    yield database
    await database.close()
