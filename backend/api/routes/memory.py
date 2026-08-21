"""Thin authenticated semantic-memory routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from backend.auth.dependencies import require_capability
from backend.auth.models import Capability, Principal
from backend.core.exceptions import ServiceNotReadyError
from backend.memory.service import MemoryService
from backend.schemas.memory import (
    MemoryCreateRequest,
    MemoryDeleteResponse,
    MemoryListResponse,
    MemoryResponse,
    MemoryType,
)

router = APIRouter(prefix="/memory", tags=["memory"])
ReadPrincipal = Annotated[Principal, Depends(require_capability(Capability.MEMORY_READ))]
WritePrincipal = Annotated[Principal, Depends(require_capability(Capability.MEMORY_WRITE))]


def get_memory_service(request: Request) -> MemoryService:
    service: MemoryService | None = getattr(request.app.state, "memory_service", None)
    if service is None:
        raise ServiceNotReadyError()
    return service


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: MemoryCreateRequest,
    principal: WritePrincipal,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryResponse:
    return await service.create(principal, request)


@router.get("", response_model=MemoryListResponse)
async def list_memory(
    principal: ReadPrincipal,
    service: Annotated[MemoryService, Depends(get_memory_service)],
    memory_type: MemoryType | None = None,
    case_reference: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> MemoryListResponse:
    items = await service.list(
        principal, memory_type=memory_type, case_reference=case_reference, limit=limit
    )
    return MemoryListResponse(items=items, count=len(items))


@router.delete("/{memory_id}", response_model=MemoryDeleteResponse)
async def delete_memory(
    memory_id: UUID,
    principal: WritePrincipal,
    service: Annotated[MemoryService, Depends(get_memory_service)],
) -> MemoryDeleteResponse:
    deleted = await service.delete_one(principal, memory_id)
    return MemoryDeleteResponse(deleted=deleted)


@router.delete("", response_model=MemoryDeleteResponse)
async def delete_all_memory(
    principal: WritePrincipal,
    service: Annotated[MemoryService, Depends(get_memory_service)],
    case_reference: Annotated[str | None, Query(max_length=100)] = None,
) -> MemoryDeleteResponse:
    deleted = await service.delete_all(principal, case_reference=case_reference)
    return MemoryDeleteResponse(deleted=deleted)
