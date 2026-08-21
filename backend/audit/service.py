"""Persist and retrieve minimised security audit events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, select

from backend.agents.models import AgentAuditEvent
from backend.auth.models import Principal
from backend.database.manager import DatabaseManager
from backend.database.models import AuditLogModel
from backend.schemas.audit import AuditEventResponse


class AuditService:
    def __init__(
        self, database: DatabaseManager, *, retention_days: int, enabled: bool = True
    ) -> None:
        self.database = database
        self.retention_days = retention_days
        self.enabled = enabled

    async def record_agent_events(
        self, principal: Principal, events: tuple[AgentAuditEvent, ...]
    ) -> None:
        if not events or not self.enabled:
            return
        created_at = datetime.now(UTC)
        expiry = created_at + timedelta(days=self.retention_days)
        rows = [
            AuditLogModel(
                id=uuid4(),
                request_id=event.request_id,
                user_id=principal.user_id,
                tenant_id=principal.tenant_id,
                event_type=event.event_type,
                agent_name=event.agent_name.value,
                tool_name=event.tool_name.value if event.tool_name else None,
                permission_level=(event.permission_level.value if event.permission_level else None),
                decision=event.decision,
                success=event.success,
                failure_category=event.failure_category,
                expires_at=expiry,
                created_at=created_at,
            )
            for event in events
        ]
        async with self.database.private_session(principal) as session:
            await session.execute(
                delete(AuditLogModel).where(AuditLogModel.expires_at <= datetime.now(UTC))
            )
            session.add_all(rows)
            await session.flush()

    async def record(
        self,
        principal: Principal,
        *,
        request_id: str,
        event_type: str,
        decision: str | None,
        success: bool,
        failure_category: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        created_at = datetime.now(UTC)
        row = AuditLogModel(
            id=uuid4(),
            request_id=request_id,
            user_id=principal.user_id,
            tenant_id=principal.tenant_id,
            event_type=event_type,
            decision=decision,
            success=success,
            failure_category=failure_category,
            expires_at=created_at + timedelta(days=self.retention_days),
            created_at=created_at,
        )
        async with self.database.private_session(principal) as session:
            await session.execute(
                delete(AuditLogModel).where(AuditLogModel.expires_at <= datetime.now(UTC))
            )
            session.add(row)
            await session.flush()

    async def list(self, principal: Principal, *, limit: int) -> list[AuditEventResponse]:
        if not self.enabled:
            return []
        async with self.database.private_session(principal) as session:
            await session.execute(
                delete(AuditLogModel).where(AuditLogModel.expires_at <= datetime.now(UTC))
            )
            rows = (
                await session.scalars(
                    select(AuditLogModel)
                    .where(AuditLogModel.expires_at > datetime.now(UTC))
                    .order_by(AuditLogModel.created_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            AuditEventResponse(
                audit_id=row.id,
                request_id=row.request_id,
                event_type=row.event_type,
                agent_name=row.agent_name,
                tool_name=row.tool_name,
                permission_level=row.permission_level,
                decision=row.decision,
                success=row.success,
                failure_category=row.failure_category,
                created_at=row.created_at,
            )
            for row in rows
        ]
