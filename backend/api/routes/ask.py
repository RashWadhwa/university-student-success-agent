"""Thin HTTP adapter for the grounded ask workflow."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_ask_service
from backend.ask.service import AskService
from backend.schemas.ask import AskRequest, AskResponse

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse, summary="Ask a grounded policy question")
async def ask(
    request: AskRequest,
    service: Annotated[AskService, Depends(get_ask_service)],
) -> AskResponse:
    result = await service.answer(
        question=request.question,
        top_k=request.top_k,
        filters=request.filters.to_domain(),
        session_id=request.session_id,
    )
    return AskResponse.from_result(result)
