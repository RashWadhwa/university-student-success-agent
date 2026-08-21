"""Staff/admin-only audit metadata route."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.audit.service import AuditService
from backend.auth.dependencies import require_capability
from backend.auth.models import Capability, Principal
from backend.core.exceptions import ServiceNotReadyError
from backend.schemas.audit import AuditListResponse

router = APIRouter(prefix="/audit", tags=["audit"])


def get_audit_service(request: Request) -> AuditService:
    service: AuditService | None = getattr(request.app.state, "audit_service", None)
    if service is None:
        raise ServiceNotReadyError()
    return service


@router.get("", response_model=AuditListResponse)
async def list_audit_events(
    principal: Annotated[Principal, Depends(require_capability(Capability.AUDIT_READ))],
    service: Annotated[AuditService, Depends(get_audit_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditListResponse:
    items = await service.list(principal, limit=limit)
    return AuditListResponse(items=items, count=len(items))
