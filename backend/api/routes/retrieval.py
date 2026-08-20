"""Thin HTTP adapter for citation-ready hybrid retrieval."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_primary_institution_name, get_retrieval_service
from backend.rag.retrieval import RetrievalService
from backend.schemas.retrieval import RetrievalSearchRequest, RetrievalSearchResponse

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post(
    "/search",
    response_model=RetrievalSearchResponse,
    summary="Search indexed policy evidence",
)
async def search(
    request: RetrievalSearchRequest,
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    primary_institution: Annotated[str, Depends(get_primary_institution_name)],
) -> RetrievalSearchResponse:
    results = await service.search(
        query=request.query,
        top_k=request.top_k,
        filters=request.filters.to_domain(default_institution=primary_institution),
        minimum_score=request.minimum_score,
        prefer_recent=request.prefer_recent,
    )
    return RetrievalSearchResponse.from_results(request.query, results)
