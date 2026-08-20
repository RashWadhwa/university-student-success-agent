"""Semantic, lexical, and deterministic hybrid retrieval."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date
from time import perf_counter

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.manager import DatabaseManager
from backend.llm.base import LLMProvider
from backend.rag.errors import RetrievalUnavailableError
from backend.rag.types import (
    FusedRetrievalResult,
    RetrievalCandidate,
    SearchFilters,
)
from backend.repositories.documents import DocumentVectorRepository

logger = logging.getLogger(__name__)
RepositoryFactory = Callable[[AsyncSession], DocumentVectorRepository]


def reciprocal_rank_fusion(
    semantic: list[RetrievalCandidate],
    keyword: list[RetrievalCandidate],
    *,
    rrf_k: int = 60,
) -> list[FusedRetrievalResult]:
    """Fuse incomparable rankings without summing their raw scores."""

    fused: dict[str, FusedRetrievalResult] = {}
    for source, ranking in (("semantic", semantic), ("keyword", keyword)):
        for rank, candidate in enumerate(ranking, start=1):
            item = fused.setdefault(
                candidate.chunk_id,
                FusedRetrievalResult(
                    candidate=candidate,
                    score=0.0,
                    evidence_score=0.0,
                ),
            )
            item.score += 1.0 / (rrf_k + rank)
            item.evidence_score = max(item.evidence_score, candidate.score)
            item.retrieval_sources.append(source)
            item.source_scores[source] = candidate.score

    ordered = sorted(fused.values(), key=lambda item: (-item.score, item.candidate.chunk_id))
    maximum = ordered[0].score if ordered else 1.0
    for item in ordered:
        item.score /= maximum
    return ordered


class RetrievalService:
    """Coordinate query embedding, PostgreSQL retrieval, fusion, and thresholds."""

    def __init__(
        self,
        *,
        database: DatabaseManager,
        provider: LLMProvider,
        embedding_dimensions: int,
        repository_factory: RepositoryFactory = DocumentVectorRepository,
    ) -> None:
        self.database = database
        self.provider = provider
        self.embedding_dimensions = embedding_dimensions
        self.repository_factory = repository_factory

    async def search(
        self,
        *,
        query: str,
        top_k: int,
        filters: SearchFilters,
        minimum_score: float,
        prefer_recent: bool,
    ) -> list[FusedRetrievalResult]:
        started = perf_counter()
        embedding_result = await self.provider.create_embeddings([query])
        if (
            len(embedding_result.embeddings) != 1
            or len(embedding_result.embeddings[0]) != self.embedding_dimensions
        ):
            raise RetrievalUnavailableError(
                details={"reason": "Query embedding dimensions were invalid."}
            )
        candidate_limit = min(max(top_k * 3, top_k), 100)
        try:
            semantic, keyword = await asyncio.gather(
                self._semantic(
                    embedding_result.embeddings[0],
                    limit=candidate_limit,
                    filters=filters,
                    minimum_score=minimum_score,
                ),
                self._keyword(query, limit=candidate_limit, filters=filters),
            )
        except SQLAlchemyError as exc:
            logger.warning(
                "Retrieval database query failed",
                extra={"error_type": type(exc).__name__},
            )
            raise RetrievalUnavailableError() from exc
        fused = [
            item
            for item in reciprocal_rank_fusion(semantic, keyword)
            if item.evidence_score >= minimum_score
        ]
        if prefer_recent:
            fused.sort(
                key=lambda item: (
                    item.score,
                    item.candidate.effective_date or date.min,
                    item.candidate.chunk_id,
                ),
                reverse=True,
            )
        results = fused[:top_k]
        logger.info(
            "hybrid_retrieval_completed",
            extra={
                "top_k": top_k,
                "semantic_candidate_count": len(semantic),
                "keyword_candidate_count": len(keyword),
                "candidate_count": len(results),
            },
        )
        logger.info(
            "retrieval_completed",
            extra={
                "top_k": top_k,
                "candidate_count": len(results),
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return results

    async def _semantic(
        self,
        embedding: list[float],
        *,
        limit: int,
        filters: SearchFilters,
        minimum_score: float,
    ) -> list[RetrievalCandidate]:
        started = perf_counter()
        async with self.database.session() as session:
            results = await self.repository_factory(session).semantic_search(
                embedding,
                limit=limit,
                filters=filters,
                minimum_score=minimum_score,
            )
        logger.info(
            "semantic_retrieval_completed",
            extra={
                "candidate_count": len(results),
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return results

    async def _keyword(
        self,
        query: str,
        *,
        limit: int,
        filters: SearchFilters,
    ) -> list[RetrievalCandidate]:
        started = perf_counter()
        async with self.database.session() as session:
            results = await self.repository_factory(session).keyword_search(
                query,
                limit=limit,
                filters=filters,
            )
        logger.info(
            "keyword_retrieval_completed",
            extra={
                "candidate_count": len(results),
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return results
