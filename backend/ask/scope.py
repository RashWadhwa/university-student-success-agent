"""Deterministic supported-domain and individual-decision classification."""

import re

from backend.ask.types import ScopeAssessment

_SUPPORTED = re.compile(
    r"\b(assessment|coursework|submission|deadline|extensions?|mitigating\s+"
    r"circumstances?|extenuating\s+circumstances?|reassessment|resit|retake|"
    r"academic\s+appeals?|appeals?|exam(?:ination)?|missed|late)\b",
    re.IGNORECASE,
)
_UNSUPPORTED = (
    re.compile(r"\b(rent|landlord|tenancy|student\s+housing|which\s+accommodation)\b", re.I),
    re.compile(r"\b(diagnos(?:e|is)|medication|medical\s+treatment|what\s+illness)\b", re.I),
    re.compile(r"\b(which|what)\s+(laptop|computer)\b", re.I),
    re.compile(r"\b(write|complete|do)\s+(my\s+)?(dissertation|essay|assignment)\b", re.I),
)
_DECISION = re.compile(
    r"\b(approve(?:d|\s+my)?|grant(?:ed|\s+my)?|will\s+(?:i|my\s+\w+)\s+"
    r"(?:get|be|succeed)|am\s+i\s+eligible|decide\s+my\s+case)\b",
    re.IGNORECASE,
)


def assess_scope(question: str) -> ScopeAssessment:
    """Classify obvious requests without spending retrieval or model calls."""

    for pattern in _UNSUPPORTED:
        if pattern.search(question):
            return ScopeAssessment(
                supported=False,
                reason=(
                    "The current service supports assessment policy, deadlines, extensions, "
                    "mitigating circumstances, reassessment, and academic appeals."
                ),
            )
    if not _SUPPORTED.search(question):
        return ScopeAssessment(
            supported=False,
            reason=("The question is outside the current assessment-policy support domain."),
        )
    return ScopeAssessment(
        supported=True,
        requires_individual_decision=bool(_DECISION.search(question)),
    )
