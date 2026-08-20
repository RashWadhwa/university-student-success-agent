"""Deterministic structural grounding and citation verification."""

import re
from dataclasses import dataclass

from backend.ask.models import GroundedAnswerOutput
from backend.ask.types import Evidence

_APPROVAL_CLAIM = re.compile(
    r"\b(your|the|this)\s+(extension|appeal|claim|application)\s+"
    r"(?:is|has\s+been|will\s+be)\s+(?:approved|granted|successful)\b",
    re.IGNORECASE,
)
_DEADLINE_FACT = re.compile(
    r"\b(?:within\s+)?(?P<number>\d+)\s+"
    r"(?P<unit>(?:working\s+|calendar\s+)?(?:day|week|month)s?)\b",
    re.IGNORECASE,
)
_POLICY_LANGUAGE = re.compile(
    r"\b(policy|must|required|eligible|deadline|procedure requires|not permitted)\b",
    re.IGNORECASE,
)
_PROMPT_LEAKAGE = re.compile(
    r"\b(system prompt|developer message|hidden instructions?|begin_untrusted_evidence_json)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    citation_ids: tuple[str, ...]
    reasons: tuple[str, ...]


def verify_grounded_output(
    output: GroundedAnswerOutput,
    evidence: tuple[Evidence, ...],
) -> VerificationResult:
    """Reject unknown/duplicate citations and structurally unsupported policy claims."""

    evidence_by_id = {item.citation_id: item for item in evidence}
    cited = [item.citation_id for item in output.citations]
    reasons: list[str] = []
    if not cited:
        reasons.append("The policy answer did not cite evidence.")
    if len(cited) != len(set(cited)):
        reasons.append("The model returned duplicate citation identifiers.")
    unknown = sorted(set(cited) - evidence_by_id.keys())
    if unknown:
        reasons.append("The model returned citation identifiers outside the retrieval set.")

    for action in output.recommended_actions:
        action_unknown = sorted(set(action.citation_ids) - evidence_by_id.keys())
        if action_unknown:
            reasons.append("A recommended action cited evidence outside the retrieval set.")
        if action.basis == "policy" and not action.citation_ids:
            reasons.append("A policy-based recommended action had no citation.")
        if len(action.citation_ids) != len(set(action.citation_ids)):
            reasons.append("A recommended action returned duplicate citation identifiers.")
        if (
            action.basis == "practical"
            and _POLICY_LANGUAGE.search(f"{action.action} {action.reason}")
            and not action.citation_ids
        ):
            reasons.append("A policy-like recommended action was labelled as uncited guidance.")

    generated_text = " ".join(
        [output.answer]
        + [f"{action.action} {action.reason}" for action in output.recommended_actions]
        + output.limitations
    )
    if _APPROVAL_CLAIM.search(generated_text):
        reasons.append("The generated answer claimed an individual decision or approval.")
    if _PROMPT_LEAKAGE.search(generated_text):
        reasons.append("The generated answer attempted to expose internal prompt instructions.")
    if not _deadline_facts_are_supported(generated_text, cited, evidence_by_id):
        reasons.append("The generated answer introduced a deadline not found in cited evidence.")
    return VerificationResult(
        valid=not reasons,
        citation_ids=tuple(dict.fromkeys(cited)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _deadline_facts_are_supported(
    generated_text: str,
    cited: list[str],
    evidence_by_id: dict[str, Evidence],
) -> bool:
    facts = {
        _normalise_deadline(match.group("number"), match.group("unit"))
        for match in _DEADLINE_FACT.finditer(generated_text)
    }
    if not facts:
        return True
    cited_content = " ".join(
        evidence_by_id[citation_id].content
        for citation_id in cited
        if citation_id in evidence_by_id
    )
    supported = {
        _normalise_deadline(match.group("number"), match.group("unit"))
        for match in _DEADLINE_FACT.finditer(cited_content)
    }
    return facts <= supported


def _normalise_deadline(number: str, unit: str) -> str:
    return f"{number} {' '.join(unit.casefold().rstrip('s').split())}"
