"""Deterministic evidence selection, freshness, sufficiency, and conflict rules."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from backend.ask.types import Evidence, EvidenceAssessment
from backend.rag.types import FusedRetrievalResult

_DEADLINE = re.compile(
    r"\b(?:within\s+)?\d+\s+(?:working\s+|calendar\s+)?(?:day|week|month)s?\b",
    re.IGNORECASE,
)
_DEADLINE_QUESTION = re.compile(r"\b(deadline|when|how\s+long|last\s+date)\b", re.I)


def assess_evidence(
    results: list[FusedRetrievalResult],
    *,
    question: str,
    minimum_count: int,
    minimum_score: float,
    maximum_chunks: int,
    today: date | None = None,
) -> EvidenceAssessment:
    """Prefer current versions and reject deterministically weak/conflicting evidence."""

    today = today or date.today()
    usable = [item for item in results if item.evidence_score >= minimum_score]
    reasons: list[str] = []
    if not usable:
        return EvidenceAssessment(
            evidence=(),
            sufficient=False,
            conflicting=False,
            max_score=max((item.evidence_score for item in results), default=0.0),
            reasons=("No retrieved passage met the evidence threshold.",),
        )

    current = [
        item
        for item in usable
        if item.candidate.effective_date is None or item.candidate.effective_date <= today
    ]
    if not current:
        return EvidenceAssessment(
            evidence=(),
            sufficient=False,
            conflicting=False,
            max_score=max(item.evidence_score for item in usable),
            reasons=("Only future-dated policy evidence was retrieved.",),
        )

    selected, older_omitted = _prefer_latest_policy_versions(current)
    selected = selected[:maximum_chunks]
    conflicting = _has_conflicting_current_evidence(selected)
    if conflicting:
        reasons.append("Current retrieved policy passages contain conflicting rules.")
    if len(selected) < minimum_count:
        reasons.append("Too few reliable policy passages were retrieved.")
    if _DEADLINE_QUESTION.search(question) and not any(
        _DEADLINE.search(item.candidate.content) for item in selected
    ):
        reasons.append("The question requires a deadline that the evidence does not state.")

    evidence = tuple(
        Evidence(
            citation_id=f"E{index}",
            chunk_id=item.candidate.chunk_id,
            document_id=item.candidate.document_id,
            title=item.candidate.title,
            section=item.candidate.section,
            page=item.candidate.page,
            content=item.candidate.content,
            score=item.score,
            evidence_score=item.evidence_score,
            retrieval_sources=tuple(item.retrieval_sources),
            version=item.candidate.version,
            effective_date=item.candidate.effective_date,
            source=item.candidate.source,
            institution=item.candidate.institution,
            corpus_tier=item.candidate.corpus_tier,
            authority_scope=item.candidate.authority_scope,
        )
        for index, item in enumerate(selected, start=1)
    )
    return EvidenceAssessment(
        evidence=evidence,
        sufficient=not reasons,
        conflicting=conflicting,
        max_score=max((item.evidence_score for item in selected), default=0.0),
        reasons=tuple(reasons),
        older_versions_omitted=older_omitted,
    )


def _policy_family(item: FusedRetrievalResult) -> str:
    candidate = item.candidate
    return (candidate.source or candidate.title).strip().casefold()


def _prefer_latest_policy_versions(
    results: list[FusedRetrievalResult],
) -> tuple[list[FusedRetrievalResult], bool]:
    grouped: dict[str, list[FusedRetrievalResult]] = defaultdict(list)
    for item in results:
        grouped[_policy_family(item)].append(item)

    selected_ids: set[str] = set()
    older_omitted = False
    for family_results in grouped.values():
        dated = [item.candidate.effective_date for item in family_results]
        known_dates = [value for value in dated if value is not None]
        newest = max(known_dates) if known_dates else None
        documents = {
            item.candidate.document_id
            for item in family_results
            if newest is None or item.candidate.effective_date == newest
        }
        selected_ids.update(documents)
        if len({item.candidate.document_id for item in family_results} - documents) > 0:
            older_omitted = True

    return (
        [item for item in results if item.candidate.document_id in selected_ids],
        older_omitted,
    )


def _has_conflicting_current_evidence(results: list[FusedRetrievalResult]) -> bool:
    families: dict[str, list[FusedRetrievalResult]] = defaultdict(list)
    for item in results:
        families[_policy_family(item)].append(item)
    for family_results in families.values():
        document_versions = {
            (item.candidate.document_id, item.candidate.version) for item in family_results
        }
        if len(document_versions) <= 1:
            continue
        deadline_rules = {
            match.group(0).casefold()
            for item in family_results
            for match in _DEADLINE.finditer(item.candidate.content)
        }
        if len(deadline_rules) > 1:
            return True
        versions = {version for _, version in document_versions if version is not None}
        if len(versions) > 1:
            return True
    return False
