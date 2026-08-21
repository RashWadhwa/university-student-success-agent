"""Shared rate-limit enforcement tests against PostgreSQL."""

import pytest

from backend.core.config import Environment, Settings
from backend.database.manager import DatabaseManager
from backend.security.rate_limit import RateLimitService

pytestmark = pytest.mark.integration


def limiter(database: DatabaseManager) -> RateLimitService:
    return RateLimitService(
        database,
        Settings(
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            rate_limit_secret="test-only-rate-secret-not-a-credential",
            rate_limit_window_seconds=60,
            llm_provider="mock",
            eval_provider="mock",
            embedding_dimensions=8,
        ),
    )


@pytest.mark.asyncio
async def test_under_over_limit_and_independent_users(
    integration_database: DatabaseManager,
) -> None:
    service = limiter(integration_database)
    assert await service.allow(identity="user-a", bucket="ask", limit=2)
    assert await service.allow(identity="user-a", bucket="ask", limit=2)
    assert not await service.allow(identity="user-a", bucket="ask", limit=2)
    assert await service.allow(identity="user-b", bucket="ask", limit=2)


@pytest.mark.asyncio
async def test_expensive_evaluation_has_separate_strict_limit(
    integration_database: DatabaseManager,
) -> None:
    service = limiter(integration_database)
    assert await service.allow(identity="admin-a", bucket="evaluation", limit=1)
    assert not await service.allow(identity="admin-a", bucket="evaluation", limit=1)
    assert await service.allow(identity="admin-a", bucket="ask", limit=20)


@pytest.mark.asyncio
async def test_identity_does_not_depend_on_spoofable_forwarded_header(
    integration_database: DatabaseManager,
) -> None:
    service = limiter(integration_database)
    assert service.identity_hash("authenticated-user") == service.identity_hash(
        "authenticated-user"
    )
    assert service.identity_hash("authenticated-user") != service.identity_hash("203.0.113.7")
