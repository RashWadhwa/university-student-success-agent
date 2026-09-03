"""Deterministic structural grounding and citation verification."""

import re
from dataclasses import dataclass

from backend.ask.models import GeneratedAction, GroundedAnswerOutput
from backend.ask.types import Evidence

# Detects an ASSERTED decision outcome ("your extension is approved"), not
# merely the co-occurrence of a subject noun and an outcome verb. A decision
# outcome immediately introduced by "if" or "whether" is a description of a
# pending/future decision or a notification process — not a claim that the
# outcome has happened — so it is excluded via lookbehind rather than by any
# broader "contains if/whether" exemption. This exclusion looks only at what
# immediately precedes the outcome phrase itself, so a sentence can still
# fail when the outcome is the asserted main clause even though it *also*
# contains "if" elsewhere (see "Your extension is approved if you submit
# evidence." and "If you provide medical evidence, your extension will be
# approved." — in both, the outcome phrase itself is not directly preceded
# by if/whether, so both are still correctly rejected).
_APPROVAL_CLAIM = re.compile(
    r"(?<!\bif\s)(?<!\bwhether\s)"
    r"\b(your|the|this)\s+"
    r"(extension|appeal|claim|application|request|mitigating circumstances)\s+"
    r"(?:is|are|has\s+been|have\s+been|was|were|will\s+be)\s+"
    r"(?:approved|granted|successful|accepted)\b",
    re.IGNORECASE,
)
_DEADLINE_FACT = re.compile(
    r"\b(?:within\s+)?(?P<number>\d+)\s+"
    r"(?P<unit>(?:working\s+|calendar\s+)?(?:day|week|month)s?)\b",
    re.IGNORECASE,
)
# Strong, obligation-bearing signals only. Bare topic nouns like "policy",
# "deadline", "evidence", or "confirmation" are deliberately excluded: an
# action can reference an already-established policy concept as context for
# generic advice ("Keep a copy of the revised deadline for your records.")
# without itself asserting a new requirement. Only these obligation markers,
# a named-form-completion instruction (_NAMED_FORM_COMPLETION below), or a
# concrete numeric deadline (_DEADLINE_FACT) make an action policy-backed.
#
# "approval"/"granted" is deliberately NOT included as a bare, context-free
# trigger: live diagnosis showed it firing on referential mentions like "any
# e-mail confirmation of approval" in generic record-keeping advice — the
# same weak-noun pattern as "confirmation" itself, not a new obligation. A
# genuine approval-dependent requirement is still caught via "must"/"require".
#
# "submit" excludes "you submit" (referencing something already/generally
# submitted, e.g. "a copy of what you submit") and generic "how to submit"
# references, while still matching the imperative "Submit the form...". A
# genuine "need to submit"/"have to submit" instruction is still caught
# independently via the need-to/have-to trigger regardless of this exclusion.
_POLICY_LANGUAGE = re.compile(
    r"\b(must|require[sd]?|needs?\s+to|(?:have|has)\s+to|"
    r"eligible|not\s+permitted|(?<!\byou\s)(?<!\bto\s)submit)\b",
    re.IGNORECASE,
)
# "Complete the Mitigating Circumstances form" is a policy-derived
# instruction regardless of the form's name; a short character window
# between "complete" and "form" catches this without needing to know any
# specific form name.
_NAMED_FORM_COMPLETION = re.compile(r"\bcomplete\b[^.\n]{0,60}\bform\b", re.IGNORECASE)
_PROMPT_LEAKAGE = re.compile(
    r"\b(system prompt|developer message|hidden instructions?|begin_untrusted_evidence_json)\b",
    re.IGNORECASE,
)
_CONTROL_INSTRUCTION = re.compile(
    r"\b(?:ignore\s+(?:the\s+)?(?:coordinator|system|previous\s+instructions?)|"
    r"call\s+(?:an?\s+)?(?:unauthori[sz]ed\s+)?tool|change\s+(?:your\s+)?role|"
    r"send\s+all\s+retrieved\s+documents|grant\s+(?:yourself|me)\s+(?:a\s+)?tool)\b",
    re.IGNORECASE,
)


# Maps each exact deterministic rejection reason to a small, fixed,
# non-sensitive diagnostic vocabulary — never the model output, question,
# prompt, or evidence text itself. Order matters: the first matching reason
# (in the order verify_grounded_output appends them) is reported. There is
# no "mismatch" code any more: the model no longer labels its own actions,
# so there is no label for it to get wrong. An uncited/misgrounded action is
# always classified the same way regardless of what field the model put it in.
_REASON_CODES: dict[str, str] = {
    "The generated answer did not cite any policy evidence.": "evidence_consistency_failure",
    "A policy fact cited evidence outside the retrieval set.": "unknown_citation",
    "A policy fact returned duplicate citation identifiers.": "evidence_consistency_failure",
    "A policy fact had no supporting citation.": "uncited_policy_action",
    "A policy-backed action cited evidence outside the retrieval set.": "unknown_citation",
    "A policy-backed action returned duplicate citation identifiers.": (
        "evidence_consistency_failure"
    ),
    "A policy-backed action had no supporting citation.": "uncited_policy_action",
    "An action returned duplicate citation identifiers.": "evidence_consistency_failure",
    "An action cited evidence outside the retrieval set.": "unknown_citation",
    "The generated answer claimed an individual decision or approval.": "approval_claim",
    "The generated answer attempted to expose internal prompt instructions.": "prompt_leakage",
    "The generated answer contained an agent-control instruction.": "control_instruction",
    "The generated answer introduced a deadline not found in cited evidence.": "invented_deadline",
}


def classify_verification_failure(reasons: tuple[str, ...]) -> str:
    """Return the safe diagnostic code for the first (primary) rejection reason."""

    if not reasons:
        return "none"
    return _REASON_CODES.get(reasons[0], "evidence_consistency_failure")


# A single bounded regeneration (same evidence, same verifier) is only
# attempted for failure modes the architecture can plausibly self-correct
# without any rule changing. Explicitly excluded: prompt_leakage and
# control_instruction (safety/injection concerns, not a missing citation)
# and evidence_consistency_failure/invented_deadline (missing citations
# entirely, or a fabricated fact not in evidence — hallucination concerns,
# not recoverable by asking the same model to relabel the same claim).
RETRY_ELIGIBLE_REASON_CODES = frozenset(
    {"uncited_policy_action", "approval_claim", "unknown_citation"}
)


def is_retryable_verification_failure(reasons: tuple[str, ...]) -> bool:
    """True only if every rejection reason (not just the primary one) is retry-eligible.

    A mixed failure with even one non-eligible reason is never retried.
    """

    if not reasons:
        return False
    return all(
        _REASON_CODES.get(reason, "evidence_consistency_failure") in RETRY_ELIGIBLE_REASON_CODES
        for reason in reasons
    )


@dataclass(frozen=True, slots=True)
class ClassifiedAction:
    """An action as the backend deterministically classified it — never as the

    model labelled it, because the model never labels its own actions.
    """

    priority: int
    action: str
    reason: str
    citation_ids: tuple[str, ...]
    kind: str  # "policy" | "practical"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    citation_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    classified_actions: tuple[ClassifiedAction, ...] = ()


def _action_is_policy_like(action: GeneratedAction) -> bool:
    """Objective, server-derived signal — the ONLY signal used to decide whether

    an action is policy-backed. The model never supplies or influences this
    decision; it only supplies action text, a reason, and evidence references.

    Only action.action (the operative instruction) is scanned — never
    action.reason. reason is explanatory rationale and may legitimately
    mention words like "policy", "deadline", or "requirement" (for example,
    to explain why a generic tip is being offered) without the action itself
    asserting a new policy requirement; scanning it produced false positives
    on genuinely generic advice (see the uncited_policy_action diagnosis).

    Within action.action, a bare topic noun is never sufficient by itself —
    only an obligation-bearing signal (must, require[sd], need/have to,
    eligible, not permitted, submit, approval/granted), a named-form
    completion instruction, or a concrete numeric deadline (e.g. "5 working
    days") makes an action policy-backed.
    """

    text = action.action
    return bool(
        _POLICY_LANGUAGE.search(text)
        or _NAMED_FORM_COMPLETION.search(text)
        or _DEADLINE_FACT.search(text)
    )


def verify_grounded_output(
    output: GroundedAnswerOutput,
    evidence: tuple[Evidence, ...],
) -> VerificationResult:
    """Reject unknown/duplicate citations and structurally unsupported policy claims.

    Classification of each action (policy-backed vs. generic) is derived here,
    deterministically, from the action's own content and its own citation_ids
    only. A citation is never inferred or borrowed from a policy_fact or from
    another action — an uncited policy-like action fails regardless of whether
    a similar, correctly cited policy_fact exists elsewhere in the same answer.
    """

    evidence_by_id = {item.citation_id: item for item in evidence}
    reasons: list[str] = []
    all_cited: list[str] = []

    for fact in output.policy_facts:
        all_cited.extend(fact.citation_ids)
        unknown = sorted(set(fact.citation_ids) - evidence_by_id.keys())
        if unknown:
            reasons.append("A policy fact cited evidence outside the retrieval set.")
        if len(fact.citation_ids) != len(set(fact.citation_ids)):
            reasons.append("A policy fact returned duplicate citation identifiers.")
        if not fact.citation_ids:
            reasons.append("A policy fact had no supporting citation.")

    classified_actions: list[ClassifiedAction] = []
    for action in output.actions:
        is_policy_like = _action_is_policy_like(action)
        unknown = sorted(set(action.citation_ids) - evidence_by_id.keys())
        duplicate = len(action.citation_ids) != len(set(action.citation_ids))
        if is_policy_like:
            all_cited.extend(action.citation_ids)
            if unknown:
                reasons.append("A policy-backed action cited evidence outside the retrieval set.")
            if duplicate:
                reasons.append("A policy-backed action returned duplicate citation identifiers.")
            if not action.citation_ids:
                reasons.append("A policy-backed action had no supporting citation.")
        else:
            # Citations are optional on generic guidance, but any citation the
            # model does attach is still held to the same hygiene checks — an
            # unknown or duplicate ID is never silently accepted just because
            # the action itself did not need to be cited.
            if action.citation_ids:
                all_cited.extend(action.citation_ids)
            if unknown:
                reasons.append("An action cited evidence outside the retrieval set.")
            if duplicate:
                reasons.append("An action returned duplicate citation identifiers.")
        classified_actions.append(
            ClassifiedAction(
                priority=action.priority,
                action=action.action,
                reason=action.reason,
                citation_ids=tuple(action.citation_ids),
                kind="policy" if is_policy_like else "practical",
            )
        )

    if not all_cited:
        reasons.append("The generated answer did not cite any policy evidence.")

    cited = list(dict.fromkeys(all_cited))
    generated_text = " ".join(
        [output.summary]
        + [fact.fact for fact in output.policy_facts]
        + [f"{action.action} {action.reason}" for action in output.actions]
        + output.limitations
    )
    if _APPROVAL_CLAIM.search(generated_text):
        reasons.append("The generated answer claimed an individual decision or approval.")
    if _PROMPT_LEAKAGE.search(generated_text):
        reasons.append("The generated answer attempted to expose internal prompt instructions.")
    if _CONTROL_INSTRUCTION.search(generated_text):
        reasons.append("The generated answer contained an agent-control instruction.")
    if not _deadline_facts_are_supported(generated_text, cited, evidence_by_id):
        reasons.append("The generated answer introduced a deadline not found in cited evidence.")
    return VerificationResult(
        valid=not reasons,
        citation_ids=tuple(cited),
        reasons=tuple(dict.fromkeys(reasons)),
        classified_actions=tuple(classified_actions),
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
