"""Tests for deterministic rank fusion and retrieval metric hooks."""

from datetime import date

from backend.rag.evaluation import (
    hit_rate_at_k,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from backend.rag.retrieval import reciprocal_rank_fusion
from backend.rag.types import RetrievalCandidate


def candidate(chunk_id: str, score: float) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=chunk_id,
        document_id="doc-1",
        content=f"content {chunk_id}",
        page=1,
        section="Evidence",
        title="Policy",
        document_type="policy",
        institution="Example University",
        version="1",
        effective_date=date(2026, 1, 1),
        review_date=None,
        source="https://example.edu/policy",
        score=score,
    )


def test_rrf_merges_overlap_and_keeps_single_source_candidates() -> None:
    semantic = [candidate("overlap", 0.9), candidate("semantic-only", 0.8)]
    keyword = [candidate("keyword-only", 0.7), candidate("overlap", 0.6)]

    results = reciprocal_rank_fusion(semantic, keyword)

    assert [item.candidate.chunk_id for item in results] == [
        "overlap",
        "keyword-only",
        "semantic-only",
    ]
    assert results[0].retrieval_sources == ["semantic", "keyword"]
    assert results[0].score == 1.0
    assert len({item.candidate.chunk_id for item in results}) == 3


def test_retrieval_metric_hooks() -> None:
    retrieved = ["a", "b", "c"]
    relevant = {"b", "d"}

    assert recall_at_k(retrieved, relevant, 2) == 0.5
    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert hit_rate_at_k(retrieved, relevant, 1) == 0.0
    assert reciprocal_rank(retrieved, relevant) == 0.5
    assert mean_reciprocal_rank([retrieved, ["d"]], [relevant, relevant]) == 0.75
