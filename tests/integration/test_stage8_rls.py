"""Real PostgreSQL RLS, memory lifecycle, tenant and audit isolation tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from backend.audit.service import AuditService
from backend.auth.models import Principal, Role
from backend.core.config import Environment, Settings
from backend.core.exceptions import ApplicationError
from backend.database.manager import DatabaseManager
from backend.database.models import DocumentModel, SemanticMemoryModel
from backend.memory.service import MemoryService
from backend.schemas.memory import MemoryCreateRequest

pytestmark = pytest.mark.integration


def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider="mock",
        eval_provider="mock",
        embedding_dimensions=8,
        memory_preference_retention_days=30,
        memory_case_retention_days=7,
    )


@pytest.mark.asyncio
async def test_private_tables_force_rls_and_session_assumes_constrained_role(
    integration_database: DatabaseManager,
) -> None:
    user = Principal(uuid4(), "tenant-a", Role.STUDENT)
    async with integration_database.session() as session:
        flags = (
            await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('semantic_memory', 'audit_logs') ORDER BY relname"
                )
            )
        ).all()
    assert flags == [("audit_logs", True, True), ("semantic_memory", True, True)]
    async with integration_database.private_session(user) as session:
        assert await session.scalar(text("SELECT current_user")) == "student_success_app"


@pytest.mark.asyncio
async def test_owner_cross_user_tenant_and_admin_rls(
    integration_database: DatabaseManager,
) -> None:
    service = MemoryService(integration_database, settings())
    user_a = Principal(uuid4(), "tenant-a", Role.STUDENT)
    user_b = Principal(uuid4(), "tenant-a", Role.STUDENT)
    other_tenant = Principal(uuid4(), "tenant-b", Role.STUDENT)
    admin = Principal(uuid4(), "tenant-a", Role.ADMIN)
    created = await service.create(
        user_a,
        MemoryCreateRequest(
            memory_type="preference",
            fact="Prefers email reminders.",
            consent=True,
            durable=True,
        ),
    )

    assert len(await service.list(user_a, memory_type=None, case_reference=None, limit=20)) == 1
    assert await service.list(user_b, memory_type=None, case_reference=None, limit=20) == []
    assert await service.list(other_tenant, memory_type=None, case_reference=None, limit=20) == []
    assert await service.list(admin, memory_type=None, case_reference=None, limit=20) == []
    with pytest.raises(ApplicationError):
        await service.create(
            user_b,
            MemoryCreateRequest(
                memory_type="preference",
                fact="Attempted cross-user supersession.",
                consent=True,
                durable=True,
                supersedes=created.memory_id,
            ),
        )
    assert await service.delete_one(user_b, created.memory_id) == 0
    assert await service.delete_one(user_a, created.memory_id) == 1


@pytest.mark.asyncio
async def test_memory_requires_consent_and_does_not_persist_transient_fact(
    integration_database: DatabaseManager,
) -> None:
    service = MemoryService(integration_database, settings())
    user = Principal(uuid4(), "tenant-a", Role.STUDENT)
    with pytest.raises(ApplicationError, match="consent"):
        await service.create(
            user,
            MemoryCreateRequest(
                memory_type="preference",
                fact="Temporary interaction detail.",
                consent=False,
                durable=False,
            ),
        )
    with pytest.raises(ApplicationError, match="Transient"):
        await service.create(
            user,
            MemoryCreateRequest(
                memory_type="preference",
                fact="Temporary interaction detail.",
                consent=True,
                durable=False,
            ),
        )
    assert await service.list(user, memory_type=None, case_reference=None, limit=20) == []


@pytest.mark.asyncio
async def test_memory_supersession_expiry_delete_all_and_public_policy_access(
    integration_database: DatabaseManager,
) -> None:
    service = MemoryService(integration_database, settings())
    user = Principal(uuid4(), "tenant-a", Role.STUDENT)
    first = await service.create(
        user,
        MemoryCreateRequest(
            memory_type="ongoing_action",
            fact="Will contact support.",
            consent=True,
            durable=True,
        ),
    )
    second = await service.create(
        user,
        MemoryCreateRequest(
            memory_type="ongoing_action",
            fact="Has contacted support.",
            consent=True,
            durable=True,
            supersedes=first.memory_id,
        ),
    )
    assert [
        item.memory_id
        for item in await service.list(user, memory_type=None, case_reference=None, limit=20)
    ] == [second.memory_id]
    async with integration_database.private_session(user) as session:
        row = await session.get(SemanticMemoryModel, second.memory_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert await service.expire_due(user) == 1
    assert await service.list(user, memory_type=None, case_reference=None, limit=20) == []
    assert await service.delete_all(user, case_reference=None) == 1
    async with integration_database.private_session(user) as session:
        assert (await session.scalars(select(DocumentModel))).all() == []


@pytest.mark.asyncio
async def test_audit_is_tenant_scoped_and_student_cannot_read(
    integration_database: DatabaseManager,
) -> None:
    audit = AuditService(integration_database, retention_days=30)
    student = Principal(uuid4(), "tenant-a", Role.STUDENT)
    staff = Principal(uuid4(), "tenant-a", Role.STAFF)
    other_staff = Principal(uuid4(), "tenant-b", Role.STAFF)
    await audit.record(
        student,
        request_id="safe-request-id",
        event_type="memory_created",
        decision="allowed",
        success=True,
    )
    assert len(await audit.list(staff, limit=20)) == 1
    assert await audit.list(other_staff, limit=20) == []
    assert await audit.list(student, limit=20) == []
