"""Stage 5 deterministic evaluation-hook tests."""

from backend.ask.evaluation import (
    citation_correctness,
    confidence_score,
    escalation_correctness,
    structural_groundedness,
)
from backend.ask.types import AskOutcome, AskResult, Citation, Confidence


def answered_result() -> AskResult:
    return AskResult(
        outcome=AskOutcome.ANSWERED,
        answer="Grounded answer.",
        recommended_actions=(),
        citations=(
            Citation(
                citation_id="E1",
                document_id="doc-1",
                chunk_id="chunk-1",
                document_title="Policy",
                section="Rules",
                page=1,
                source=None,
                excerpt="Evidence.",
                version=None,
                effective_date=None,
                retrieval_sources=("semantic",),
            ),
        ),
        confidence=Confidence.MEDIUM,
        limitations=(),
        requires_human_support=False,
        human_support_reason=None,
        request_id="request-1",
        retrieved_count=1,
        evidence_count=1,
        citation_verification_passed=True,
    )


def test_stage_five_evaluation_hooks() -> None:
    result = answered_result()

    assert citation_correctness(result, {"chunk-1"}) == 1.0
    assert structural_groundedness(result) == 1.0
    assert escalation_correctness(result, escalation_expected=False) == 1.0
    assert confidence_score(result) == 0.6
