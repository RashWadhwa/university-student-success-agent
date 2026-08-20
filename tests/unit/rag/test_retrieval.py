"""Unit tests for retrieval coordination, limits, thresholds, and filters."""

from contextlib import asynccontextmanager
from datetime import date
from typing import Any, ClassVar

import pytest

from backend.llm.providers.mock_provider import MockLLMProvider
from backend.rag.retrieval import RetrievalService
from backend.rag.types import RetrievalCandidate, SearchFilters


def candidate(chunk_id: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id="document-id",
        content=f"Evidence for {chunk_id}",
        page=2,
        section="Mitigating circumstances",
        title="Assessment Policy",
        document_type="policy",
        institution="Example University",
        version="2",
        effective_date=date(2026, 9, 1),
        review_date=None,
        source="policy-source",
        score=score,
    )


class FakeDatabase:
    @asynccontextmanager
    async def session(self) -> Any:
        yield object()


class FakeRepository:
    semantic: ClassVar[list[RetrievalCandidate]] = [
        candidate("semantic", 0.9),
        candidate("overlap", 0.8),
    ]
    keyword: ClassVar[list[RetrievalCandidate]] = [
        candidate("keyword", 0.7),
        candidate("overlap", 0.6),
    ]
    seen_filters: SearchFilters | None = None

    def __init__(self, session: object) -> None:
        del session

    async def semantic_search(
        self,
        embedding: list[float],
        *,
        limit: int,
        filters: SearchFilters,
        minimum_score: float,
    ) -> list[RetrievalCandidate]:
        del embedding, limit
        self.__class__.seen_filters = filters
        return [item for item in self.semantic if item.score >= minimum_score]

    async def keyword_search(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters,
    ) -> list[RetrievalCandidate]:
        del query, limit
        self.__class__.seen_filters = filters
        return self.keyword


@pytest.mark.asyncio
async def test_search_fuses_deduplicates_filters_and_bounds_top_k() -> None:
    filters = SearchFilters(document_type="policy", institution="Example University")
    service = RetrievalService(
        database=FakeDatabase(),  # type: ignore[arg-type]
        provider=MockLLMProvider(embedding_dimensions=3),
        embedding_dimensions=3,
        repository_factory=FakeRepository,  # type: ignore[arg-type]
    )

    results = await service.search(
        query="mitigating circumstances evidence",
        top_k=2,
        filters=filters,
        minimum_score=0.0,
        prefer_recent=False,
    )

    assert len(results) == 2
    assert results[0].candidate.chunk_id == "overlap"
    assert results[0].retrieval_sources == ["semantic", "keyword"]
    assert FakeRepository.seen_filters == filters


@pytest.mark.asyncio
async def test_threshold_can_return_empty_results() -> None:
    service = RetrievalService(
        database=FakeDatabase(),  # type: ignore[arg-type]
        provider=MockLLMProvider(embedding_dimensions=3),
        embedding_dimensions=3,
        repository_factory=FakeRepository,  # type: ignore[arg-type]
    )

    results = await service.search(
        query="unmatched query",
        top_k=5,
        filters=SearchFilters(source="policy-source"),
        minimum_score=0.95,
        prefer_recent=False,
    )

    assert results == []
