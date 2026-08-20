"""Small retrieval metric hooks for the Stage 5 evaluation framework."""

from collections.abc import Iterable


def recall_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = set(list(retrieved)[:k]) & relevant
    return len(hits) / len(relevant)


def precision_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    selected = list(retrieved)[:k]
    if not selected:
        return 0.0
    return len(set(selected) & relevant) / len(selected)


def hit_rate_at_k(retrieved: Iterable[str], relevant: set[str], k: int) -> float:
    return float(bool(set(list(retrieved)[:k]) & relevant))


def reciprocal_rank(retrieved: Iterable[str], relevant: set[str]) -> float:
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank(
    ranked_results: Iterable[Iterable[str]],
    relevant_sets: Iterable[set[str]],
) -> float:
    scores = [
        reciprocal_rank(retrieved, relevant)
        for retrieved, relevant in zip(ranked_results, relevant_sets, strict=True)
    ]
    return sum(scores) / len(scores) if scores else 0.0
