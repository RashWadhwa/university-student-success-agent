"""Scope, sufficiency, freshness, and conflict rule tests."""

from datetime import date

from backend.ask.evidence import assess_evidence
from backend.ask.scope import assess_scope
from backend.rag.types import FusedRetrievalResult, RetrievalCandidate


def result(
    chunk_id: str,
    *,
    content: str = "Extensions may be requested under the assessment policy.",
    evidence_score: float = 0.9,
    document_id: str = "doc-1",
    version: str = "1",
    effective_date: date | None = date(2025, 1, 1),
    source: str = "https://example.edu/policy",
) -> FusedRetrievalResult:
    return FusedRetrievalResult(
        candidate=RetrievalCandidate(
            chunk_id=chunk_id,
            document_id=document_id,
            content=content,
            page=1,
            section="Extensions",
            title="Assessment Policy",
            document_type="academic_policy",
            institution="Example University",
            version=version,
            effective_date=effective_date,
            review_date=None,
            source=source,
            score=evidence_score,
        ),
        score=1.0,
        evidence_score=evidence_score,
        retrieval_sources=["semantic", "keyword"],
        source_scores={"semantic": evidence_score, "keyword": 0.4},
    )


def test_scope_supports_assessment_domain_and_marks_individual_decisions() -> None:
    supported = assess_scope("I missed an assessment because I was ill. What should I do?")
    decision = assess_scope("Will my academic appeal be approved?")

    assert supported.supported is True
    assert decision.supported is True
    assert decision.requires_individual_decision is True


def test_scope_rejects_clear_unsupported_and_medical_requests() -> None:
    assert assess_scope("What laptop should I buy?").supported is False
    assert assess_scope("Can you diagnose my illness?").supported is False
    assert assess_scope("Write my dissertation for me.").supported is False


def test_zero_and_weak_results_are_insufficient() -> None:
    empty = assess_evidence(
        [],
        question="Can I request an extension?",
        minimum_count=1,
        minimum_score=0.5,
        maximum_chunks=5,
    )
    weak = assess_evidence(
        [result("weak", evidence_score=0.49)],
        question="Can I request an extension?",
        minimum_count=1,
        minimum_score=0.5,
        maximum_chunks=5,
    )

    assert empty.sufficient is False
    assert weak.sufficient is False
    assert weak.evidence == ()


def test_latest_effective_policy_version_is_preferred() -> None:
    assessment = assess_evidence(
        [
            result(
                "old",
                document_id="old-doc",
                version="1",
                effective_date=date(2024, 1, 1),
            ),
            result(
                "new",
                document_id="new-doc",
                version="2",
                effective_date=date(2025, 1, 1),
            ),
        ],
        question="Can I request an extension?",
        minimum_count=1,
        minimum_score=0.5,
        maximum_chunks=5,
        today=date(2026, 1, 1),
    )

    assert assessment.sufficient is True
    assert [item.chunk_id for item in assessment.evidence] == ["new"]
    assert assessment.older_versions_omitted is True


def test_conflicting_current_versions_are_rejected() -> None:
    assessment = assess_evidence(
        [
            result(
                "five-days",
                content="The claim must be submitted within 5 working days.",
                document_id="doc-a",
                version="1",
            ),
            result(
                "ten-days",
                content="The claim must be submitted within 10 working days.",
                document_id="doc-b",
                version="2",
            ),
        ],
        question="What is the deadline for mitigating circumstances?",
        minimum_count=1,
        minimum_score=0.5,
        maximum_chunks=5,
        today=date(2026, 1, 1),
    )

    assert assessment.sufficient is False
    assert assessment.conflicting is True


def test_unstated_critical_deadline_requires_clarification() -> None:
    assessment = assess_evidence(
        [result("procedure", content="Use the mitigating circumstances procedure.")],
        question="When is the mitigating circumstances deadline?",
        minimum_count=1,
        minimum_score=0.5,
        maximum_chunks=5,
    )

    assert assessment.sufficient is False
    assert "deadline" in " ".join(assessment.reasons).lower()


def test_only_configured_maximum_evidence_is_selected() -> None:
    assessment = assess_evidence(
        [result(f"chunk-{index}") for index in range(5)],
        question="Can I request an assessment extension?",
        minimum_count=1,
        minimum_score=0.5,
        maximum_chunks=2,
    )

    assert assessment.sufficient is True
    assert len(assessment.evidence) == 2
