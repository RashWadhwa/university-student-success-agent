"""Data-minimising semantic memory policy and persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from backend.auth.models import Principal
from backend.core.config import Settings
from backend.core.context import get_request_id
from backend.core.exceptions import ApplicationError
from backend.database.manager import DatabaseManager
from backend.database.models import AuditLogModel, SemanticMemoryModel
from backend.schemas.memory import MemoryCreateRequest, MemoryResponse, MemoryType


class MemoryService:
    """Write only explicit durable facts; retrieve only caller-scoped records."""

    def __init__(self, database: DatabaseManager, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    async def create(self, principal: Principal, request: MemoryCreateRequest) -> MemoryResponse:
        if not request.consent:
            raise ApplicationError(
                code="MEMORY_CONSENT_REQUIRED",
                message="Explicit consent is required before memory can be saved.",
                status_code=422,
            )
        if not request.durable:
            raise ApplicationError(
                code="MEMORY_NOT_DURABLE",
                message="Transient interaction details cannot be saved as durable memory.",
                status_code=422,
            )
        if len(request.fact) > self.settings.memory_max_fact_chars:
            raise ApplicationError(
                code="MEMORY_TOO_LARGE",
                message="The memory fact is too large.",
                status_code=422,
            )
        now = datetime.now(UTC)
        retention_days = (
            self.settings.memory_case_retention_days
            if request.memory_type in {MemoryType.CASE_SUMMARY, MemoryType.ONGOING_ACTION}
            else self.settings.memory_preference_retention_days
        )
        row = SemanticMemoryModel(
            id=uuid4(),
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            memory_type=request.memory_type.value,
            fact=request.fact,
            source_type=request.source_type,
            source_reference=request.source_reference,
            confidence=request.confidence,
            consent_scope=request.consent_scope,
            retention_category=(
                "case"
                if retention_days == self.settings.memory_case_retention_days
                else "preference"
            ),
            case_reference=request.case_reference,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=retention_days),
            is_active=True,
        )
        async with self.database.private_session(principal) as session:
            await session.execute(
                delete(SemanticMemoryModel).where(
                    SemanticMemoryModel.expires_at <= datetime.now(UTC)
                )
            )
            if request.supersedes is not None:
                old = await session.scalar(
                    select(SemanticMemoryModel).where(
                        SemanticMemoryModel.id == request.supersedes,
                        SemanticMemoryModel.is_active.is_(True),
                    )
                )
                if old is None:
                    raise ApplicationError(
                        code="MEMORY_NOT_FOUND",
                        message="The memory was not found.",
                        status_code=404,
                    )
                old.is_active = False
                old.superseded_by = row.id
            session.add(row)
            session.add(self._audit_row(principal, "memory_created", "consented", True))
            await session.flush()
        return self._response(row)

    async def list(
        self,
        principal: Principal,
        *,
        memory_type: MemoryType | None,
        case_reference: str | None,
        limit: int,
    ) -> list[MemoryResponse]:
        await self.expire_due(principal)
        query = select(SemanticMemoryModel).where(
            SemanticMemoryModel.is_active.is_(True),
            SemanticMemoryModel.expires_at > datetime.now(UTC),
        )
        if memory_type is not None:
            query = query.where(SemanticMemoryModel.memory_type == memory_type.value)
        if case_reference is not None:
            query = query.where(SemanticMemoryModel.case_reference == case_reference)
        query = query.order_by(SemanticMemoryModel.updated_at.desc()).limit(limit)
        async with self.database.private_session(principal) as session:
            rows = (await session.scalars(query)).all()
        return [self._response(row) for row in rows]

    async def delete_one(self, principal: Principal, memory_id: UUID) -> int:
        async with self.database.private_session(principal) as session:
            result = await session.execute(
                delete(SemanticMemoryModel).where(SemanticMemoryModel.id == memory_id)
            )
            deleted = int(result.rowcount or 0)
            session.add(
                self._audit_row(
                    principal,
                    "memory_deleted",
                    "single",
                    deleted == 1,
                    None if deleted == 1 else "not_found",
                )
            )
        return deleted

    async def delete_all(self, principal: Principal, *, case_reference: str | None) -> int:
        statement = delete(SemanticMemoryModel)
        if case_reference is not None:
            statement = statement.where(SemanticMemoryModel.case_reference == case_reference)
        async with self.database.private_session(principal) as session:
            result = await session.execute(statement)
            session.add(
                self._audit_row(
                    principal, "memory_deleted", "case" if case_reference else "all", True
                )
            )
        return int(result.rowcount or 0)

    async def expire_due(self, principal: Principal) -> int:
        async with self.database.private_session(principal) as session:
            result = await session.execute(
                delete(SemanticMemoryModel).where(
                    SemanticMemoryModel.expires_at <= datetime.now(UTC)
                )
            )
        return int(result.rowcount or 0)

    @staticmethod
    def _response(row: SemanticMemoryModel) -> MemoryResponse:
        return MemoryResponse(
            memory_id=row.id,
            memory_type=MemoryType(row.memory_type),
            fact=row.fact,
            source_type=row.source_type,
            source_reference=row.source_reference,
            confidence=row.confidence,
            consent_scope=row.consent_scope,
            retention_category=row.retention_category,
            case_reference=row.case_reference,
            created_at=row.created_at,
            updated_at=row.updated_at,
            expires_at=row.expires_at,
            superseded_by=row.superseded_by,
            is_active=row.is_active,
        )

    def _audit_row(
        self,
        principal: Principal,
        event_type: str,
        decision: str,
        success: bool,
        failure_category: str | None = None,
    ) -> AuditLogModel:
        created_at = datetime.now(UTC)
        return AuditLogModel(
            id=uuid4(),
            request_id=get_request_id(),
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            event_type=event_type,
            decision=decision,
            success=success,
            failure_category=failure_category,
            expires_at=created_at + timedelta(days=self.settings.audit_retention_days),
            created_at=created_at,
        )
