"""Deterministic policy-artifact and final agent-workflow verification."""

from backend.agents.models import (
    AgentEvidence,
    PolicyAnalysisOutput,
    StudentSupportOutput,
    ToolInvocationRecord,
    VerificationOutput,
)
from backend.ask.models import GroundedAnswerOutput
from backend.ask.verification import verify_grounded_output


class WorkflowVerifier:
    """Fail closed on citations, claims, deadlines, permissions, or unsafe leakage."""

    def verify_policy_analysis(
        self,
        analysis: PolicyAnalysisOutput,
        evidence: list[AgentEvidence],
    ) -> VerificationOutput:
        evidence_ids = {item.citation_id for item in evidence}
        cited: list[str] = []
        texts: list[str] = []
        for item in (
            analysis.findings
            + analysis.deadlines
            + analysis.evidence_requirements
            + analysis.exceptions
        ):
            cited.extend(item.citation_ids)
            texts.append(item.statement)
            if hasattr(item, "deadline"):
                texts.append(item.deadline)
        for conflict in analysis.conflicts:
            cited.extend(conflict.citation_ids)
            texts.append(conflict.description)
        unknown = set(cited) - evidence_ids
        if unknown:
            return VerificationOutput(
                valid=False,
                failure_categories=["unknown_policy_citation"],
            )
        if not cited and not analysis.uncertainties:
            return VerificationOutput(valid=False, failure_categories=["uncited_policy_output"])
        if not cited:
            return VerificationOutput(valid=True, citation_ids=[])
        synthetic = GroundedAnswerOutput(
            summary=" ".join(texts),
            policy_facts=[{"fact": " ".join(texts), "citation_ids": list(dict.fromkeys(cited))}],
            actions=[],
            limitations=list(analysis.uncertainties),
            confidence="low",
            requires_human_support=bool(analysis.uncertainties or analysis.conflicts),
            human_support_reason=None,
        )
        grounded = verify_grounded_output(
            synthetic,
            tuple(item.to_domain() for item in evidence),
        )
        return VerificationOutput(
            valid=grounded.valid,
            citation_ids=list(grounded.citation_ids),
            failure_categories=[] if grounded.valid else ["policy_grounding_failed"],
        )

    def verify_final(
        self,
        *,
        support: StudentSupportOutput,
        analysis: PolicyAnalysisOutput,
        evidence: list[AgentEvidence],
        tool_invocations: list[ToolInvocationRecord],
    ) -> VerificationOutput:
        if any(not item.authorised or not item.success for item in tool_invocations):
            return VerificationOutput(
                valid=False,
                failure_categories=["unauthorised_or_failed_tool"],
            )
        policy_check = self.verify_policy_analysis(analysis, evidence)
        if not policy_check.valid:
            return policy_check
        analysed_ids = set(policy_check.citation_ids)
        support_ids = set(support.citation_ids)
        support_action_ids = {
            citation_id for action in support.actions for citation_id in action.citation_ids
        }
        if not support_ids <= analysed_ids or not support_action_ids <= analysed_ids:
            return VerificationOutput(
                valid=False,
                failure_categories=["support_used_unanalysed_evidence"],
            )
        # support.actions still carries the specialist's own self-declared
        # `basis`, but it is deliberately not read here: classification is
        # the shared verifier's job, derived from content alone, exactly as
        # for the baseline contract. This also means every action's own
        # citation_ids are validated uniformly below, regardless of basis —
        # no separate defensive check is needed for either label.
        generated = GroundedAnswerOutput(
            summary=support.answer,
            policy_facts=[{"fact": support.answer, "citation_ids": support.citation_ids}],
            actions=[
                {
                    "priority": item.priority,
                    "action": item.action,
                    "reason": item.reason,
                    "citation_ids": item.citation_ids,
                }
                for item in support.actions
            ],
            limitations=support.limitations,
            confidence="low",
            requires_human_support=support.requires_human_support,
            human_support_reason=support.human_support_reason,
        )
        grounded = verify_grounded_output(
            generated,
            tuple(item.to_domain() for item in evidence),
        )
        return VerificationOutput(
            valid=grounded.valid,
            citation_ids=list(grounded.citation_ids),
            failure_categories=[] if grounded.valid else ["final_grounding_failed"],
        )
