"""Thin HTTP adapter for the grounded ask workflow."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends

from backend.agents.service import AgenticAskService
from backend.api.dependencies import (
    get_agentic_ask_service,
    get_ask_service,
    get_observability,
    get_primary_institution_name,
)
from backend.api.routes.audit import get_audit_service
from backend.ask.service import AskService
from backend.audit.service import AuditService
from backend.auth.dependencies import get_current_principal
from backend.auth.models import Principal
from backend.core.context import get_request_id
from backend.observability.base import ObservabilityService
from backend.observability.events import record_ask_result, record_ask_started
from backend.schemas.agentic import AgenticAskResponse
from backend.schemas.ask import AskRequest, AskResponse

router = APIRouter(tags=["ask"])
logger = logging.getLogger(__name__)


def _log_authenticated_request(principal: Principal, *, workflow_mode: str) -> None:
    """Safe boundary log: proves auth/capability passed without identity data.

    Reaching this call is itself proof the request passed both
    get_current_principal and the router-level require_capability check —
    if either had failed, a 401/403 would already have been raised before
    the route body ran. Never logs tokens, emails, user IDs, or raw claims.
    """

    logger.info(
        "ask_route_authenticated",
        extra={
            "authenticated": True,
            "role": principal.role.value,
            "capability_check": "passed",
            "workflow_mode": workflow_mode,
            "request_id": get_request_id(),
        },
    )


@router.post("/ask", response_model=AskResponse, summary="Ask a grounded policy question")
async def ask(
    request: AskRequest,
    service: Annotated[AskService, Depends(get_ask_service)],
    observability: Annotated[ObservabilityService, Depends(get_observability)],
    primary_institution: Annotated[str, Depends(get_primary_institution_name)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> AskResponse:
    _log_authenticated_request(principal, workflow_mode="baseline")
    await record_ask_started(
        observability,
        request_id=get_request_id(),
        workflow_mode="baseline",
        input_length=len(request.question),
    )
    result = await service.answer(
        question=request.question,
        top_k=request.top_k,
        filters=request.filters.to_domain(default_institution=primary_institution),
        session_id=request.session_id,
    )
    trace_id = await record_ask_result(observability, result)
    await audit.record(
        principal,
        request_id=get_request_id(),
        event_type="baseline_workflow_completed",
        decision=result.outcome.value,
        success=result.outcome.value == "answered",
    )
    return AskResponse.from_result(result).model_copy(update={"trace_id": trace_id})


@router.post(
    "/ask/agentic",
    response_model=AgenticAskResponse,
    summary="Ask a bounded multi-agent policy question",
    description=(
        "Runs a fixed, permissioned specialist workflow for multi-part requests and delegates "
        "simple requests to the unchanged baseline workflow."
    ),
)
async def ask_agentic(
    request: AskRequest,
    service: Annotated[AgenticAskService, Depends(get_agentic_ask_service)],
    observability: Annotated[ObservabilityService, Depends(get_observability)],
    primary_institution: Annotated[str, Depends(get_primary_institution_name)],
    principal: Annotated[Principal, Depends(get_current_principal)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> AgenticAskResponse:
    _log_authenticated_request(principal, workflow_mode="agentic")
    await record_ask_started(
        observability,
        request_id=get_request_id(),
        workflow_mode="agentic",
        input_length=len(request.question),
    )
    result = await service.answer(
        question=request.question,
        top_k=request.top_k,
        filters=request.filters.to_domain(default_institution=primary_institution),
        session_id=request.session_id,
    )
    trace_id = await record_ask_result(observability, result)
    await audit.record_agent_events(principal, result.audit_events)
    return AgenticAskResponse.from_result(result).model_copy(update={"trace_id": trace_id})
