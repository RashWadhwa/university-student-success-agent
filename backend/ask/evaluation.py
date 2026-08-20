"""Deterministic Stage 5 evaluation hooks without an LLM judge."""

from backend.ask.types import AskResult


def citation_correctness(result: AskResult, expected_chunk_ids: set[str]) -> float:
    if not result.citations:
        return 0.0
    correct = sum(item.chunk_id in expected_chunk_ids for item in result.citations)
    return correct / len(result.citations)


def structural_groundedness(result: AskResult) -> float:
    if result.outcome != "answered":
        return float(not result.answer or result.requires_human_support)
    return float(result.citation_verification_passed and bool(result.citations))


def escalation_correctness(result: AskResult, *, escalation_expected: bool) -> float:
    return float(result.requires_human_support is escalation_expected)


def confidence_score(result: AskResult) -> float:
    return {"low": 0.25, "medium": 0.6, "high": 0.9}[result.confidence]
