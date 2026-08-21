"""Bounded state-machine orchestration for the agentic ask endpoint."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from hashlib import sha256
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel

from backend.agents.coordinator import Coordinator
from backend.agents.errors import AgentLimitError, AgentWorkflowError
from backend.agents.models import (
    AgentAuditEvent,
    AgentEvidence,
    CoordinatorDecision,
    CoordinatorInput,
    PolicyAnalysisOutput,
    PolicyAnalystInput,
    RetrievalAgentInput,
    RetrievalAgentOutput,
    StudentSupportInput,
    StudentSupportOutput,
    ToolInvocationRecord,
    VerificationOutput,
)
from backend.agents.registry import AgentRegistry
from backend.agents.specialists import (
    PolicyAnalyst,
    RetrievalSpecialist,
    StudentSupportSpecialist,
)
from backend.agents.tools import ToolContext
from backend.agents.types import (
    AgenticAskResult,
    AgentName,
    WorkflowMode,
    WorkflowState,
    WorkflowStatus,
)
from backend.agents.verification import WorkflowVerifier
from backend.ask.scope import assess_scope
from backend.ask.service import AskService
from backend.ask.types import (
    AskOutcome,
    AskResult,
    Confidence,
    EvidenceAssessment,
    RecommendedAction,
)
from backend.core.context import get_request_id
from backend.rag.types import SearchFilters
from backend.schemas.retrieval import RetrievalFilters

logger = logging.getLogger(__name__)
OutputT = TypeVar("OutputT", bound=BaseModel)


class AgenticAskService:
    """Execute a finite coordinator→specialists→verifier state machine."""

    def __init__(
        self,
        *,
        baseline: AskService,
        coordinator: Coordinator,
        registry: AgentRegistry,
        retrieval_specialist: RetrievalSpecialist,
        policy_analyst: PolicyAnalyst,
        support_specialist: StudentSupportSpecialist,
        verifier: WorkflowVerifier,
        maximum_tasks: int,
        maximum_tool_calls: int,
        maximum_evidence_items: int,
        maximum_provider_calls: int,
    ) -> None:
        self.baseline = baseline
        self.coordinator = coordinator
        self.registry = registry
        self.retrieval_specialist = retrieval_specialist
        self.policy_analyst = policy_analyst
        self.support_specialist = support_specialist
        self.verifier = verifier
        self.maximum_tasks = maximum_tasks
        self.maximum_tool_calls = maximum_tool_calls
        self.maximum_evidence_items = maximum_evidence_items
        self.maximum_provider_calls = maximum_provider_calls

    async def answer(
        self,
        *,
        question: str,
        top_k: int | None,
        filters: SearchFilters,
        session_id: str | None = None,
    ) -> AgenticAskResult:
        del session_id
        started = perf_counter()
        request_id = get_request_id()
        cleaned = question.strip()
        resolved_top_k = top_k if top_k is not None else self.baseline.default_top_k
        self.baseline.validate_request(cleaned, resolved_top_k)
        state = WorkflowState(
            question=cleaned,
            top_k=resolved_top_k,
            filters=filters,
            request_id=request_id,
            scope=assess_scope(cleaned),
        )
        logger.info("agent_workflow_started", extra={"query_length": len(cleaned)})

        try:
            decision = self._plan_once(
                state,
                CoordinatorInput(
                    question=cleaned,
                    top_k=resolved_top_k,
                    filters=RetrievalFilters.model_validate(asdict(filters)),
                ),
            )
            state.plan = decision.plan
            self._record_agent(state, AgentName.COORDINATOR)
            self._audit(
                state,
                agent=AgentName.COORDINATOR,
                event="coordinator_completed",
                success=True,
                decision=(
                    "unsupported"
                    if not decision.scope_supported
                    else ("baseline" if decision.plan and decision.plan.use_baseline else "agentic")
                ),
            )
            logger.info(
                "coordinator_completed",
                extra={
                    "scope_supported": decision.scope_supported,
                    "workflow_mode": (
                        "baseline"
                        if decision.plan is None or decision.plan.use_baseline
                        else "agentic"
                    ),
                },
            )
        except Exception as exc:
            return self._safe_failure(
                state,
                started,
                outcome=AskOutcome.TEMPORARILY_UNAVAILABLE,
                category="coordinator_failure",
                error_type=type(exc).__name__,
            )

        if not decision.scope_supported or (decision.plan and decision.plan.use_baseline):
            baseline_result = await self.baseline.answer(
                question=cleaned,
                top_k=resolved_top_k,
                filters=filters,
            )
            provider_calls = int(baseline_result.evaluation.get("provider_calls", 0))
            if provider_calls > self.maximum_provider_calls:
                return self._safe_failure(
                    state,
                    started,
                    outcome=AskOutcome.TEMPORARILY_UNAVAILABLE,
                    category="provider_call_limit",
                )
            self._transition_terminal(state, self._status_for_outcome(baseline_result.outcome))
            return AgenticAskResult(
                result=baseline_result,
                workflow_mode=WorkflowMode.BASELINE_DELEGATED,
                agents_used=tuple(state.agents_used),
                tool_calls=0,
                provider_calls=provider_calls,
                duration_ms=(perf_counter() - started) * 1000,
                verification_passed=baseline_result.citation_verification_passed,
                terminal_state=state.status,
                audit_events=tuple(state.audit_events),
            )

        plan = decision.plan
        if plan is None:  # guarded by CoordinatorDecision; defensive fail-closed check
            return self._safe_failure(
                state,
                started,
                outcome=AskOutcome.TEMPORARILY_UNAVAILABLE,
                category="invalid_plan",
            )
        try:
            self.coordinator.validate_plan(plan)
            if len(plan.tasks) > self.maximum_tasks:
                raise AgentLimitError(details={"limit": "tasks"})
            tool_context = ToolContext(
                request_id=request_id,
                maximum_calls=self.maximum_tool_calls,
            )
            retrieval_request = RetrievalAgentInput(
                query=cleaned,
                objective=plan.tasks[0].objective,
                top_k=min(resolved_top_k, self.maximum_evidence_items),
                filters=RetrievalFilters.model_validate(asdict(filters)),
            )
            retrieval_output = await self._run_agent(
                state,
                AgentName.RETRIEVAL,
                lambda: self.retrieval_specialist.execute(retrieval_request, tool_context),
                action_input=retrieval_request,
                provider_call=True,
            )
            state.tool_calls = tool_context.call_count
            state.audit_events.extend(tool_context.audit_events)
            if not isinstance(retrieval_output, RetrievalAgentOutput):
                raise AgentWorkflowError(details={"reason": "invalid_retrieval_output"})
            if not retrieval_output.sufficient:
                return self._safe_failure(
                    state,
                    started,
                    outcome=AskOutcome.INSUFFICIENT_EVIDENCE,
                    category=(
                        "conflicting_evidence"
                        if retrieval_output.conflicting
                        else "insufficient_evidence"
                    ),
                    retrieved_count=retrieval_output.retrieved_count,
                    tool_calls=tool_context.call_count,
                )
            state.evidence = tuple(item.to_domain() for item in retrieval_output.evidence)

            policy_request = PolicyAnalystInput(
                objective=plan.tasks[1].objective,
                evidence=retrieval_output.evidence,
            )
            analysis = await self._run_agent(
                state,
                AgentName.POLICY_ANALYST,
                lambda: self.policy_analyst.execute(policy_request),
                action_input=policy_request,
                provider_call=True,
            )
            state.policy_analysis = analysis
            policy_verification = self.verifier.verify_policy_analysis(
                analysis, retrieval_output.evidence
            )
            if not policy_verification.valid or analysis.conflicts:
                return self._safe_failure(
                    state,
                    started,
                    outcome=AskOutcome.VERIFICATION_FAILED,
                    category=(
                        "conflicting_specialist_output"
                        if analysis.conflicts
                        else "policy_verification_failure"
                    ),
                    retrieved_count=retrieval_output.retrieved_count,
                    tool_calls=tool_context.call_count,
                )

            support_request = StudentSupportInput(
                intent=plan.intent,
                policy_analysis=analysis,
                requires_individual_decision=plan.requires_human_support,
            )
            support = await self._run_agent(
                state,
                AgentName.STUDENT_SUPPORT,
                lambda: self.support_specialist.execute(support_request),
                action_input=support_request,
                provider_call=True,
            )
            state.support_output = support
            self._record_agent(state, AgentName.VERIFIER)
            final_verification = self._verify_final_once(
                state,
                support=support,
                analysis=analysis,
                evidence=retrieval_output.evidence,
                tool_invocations=tool_context.invocations,
            )
            self._audit(
                state,
                agent=AgentName.VERIFIER,
                event="verification_completed",
                success=final_verification.valid,
                decision="accepted" if final_verification.valid else "rejected",
                failure=(
                    None if final_verification.valid else final_verification.failure_categories[0]
                ),
            )
            logger.info(
                "verification_completed",
                extra={"verified": final_verification.valid},
            )
            if not final_verification.valid:
                return self._safe_failure(
                    state,
                    started,
                    outcome=AskOutcome.VERIFICATION_FAILED,
                    category="final_verification_failure",
                    retrieved_count=retrieval_output.retrieved_count,
                    tool_calls=tool_context.call_count,
                )

            evidence_by_id = {item.citation_id: item for item in state.evidence}
            assessment = EvidenceAssessment(
                evidence=state.evidence,
                sufficient=True,
                conflicting=False,
                max_score=retrieval_output.max_score,
                older_versions_omitted=retrieval_output.older_versions_omitted,
            )
            confidence = self.baseline.confidence_for_assessment(assessment)
            requires_human = bool(
                plan.requires_human_support
                or support.requires_human_support
                or analysis.uncertainties
            )
            if requires_human:
                confidence = Confidence.LOW
            limitations = list(support.limitations) + list(analysis.uncertainties)
            if any(item.authority_scope.value == "sector_guidance" for item in state.evidence):
                limitations.append(
                    "Secondary sector guidance is contextual and does not replace the primary "
                    "institution's policy."
                )
            if retrieval_output.older_versions_omitted:
                limitations.append(
                    "Older retrieved policy versions were omitted in favour of current evidence."
                )
            human_reason = None
            if plan.requires_human_support:
                human_reason = (
                    "University staff must make decisions about individual eligibility or approval."
                )
            elif requires_human:
                human_reason = (
                    "The verified policy findings do not resolve every aspect of the "
                    "individual case."
                )
            result = AskResult(
                outcome=AskOutcome.ANSWERED,
                answer=support.answer,
                recommended_actions=tuple(
                    RecommendedAction(
                        priority=item.priority,
                        action=item.action,
                        reason=item.reason,
                    )
                    for item in sorted(support.actions, key=lambda item: item.priority)
                ),
                citations=tuple(
                    self.baseline.citation_for_evidence(evidence_by_id[citation_id])
                    for citation_id in final_verification.citation_ids
                ),
                confidence=confidence,
                limitations=tuple(dict.fromkeys(limitations)),
                requires_human_support=requires_human,
                human_support_reason=human_reason,
                request_id=request_id,
                retrieved_count=retrieval_output.retrieved_count,
                evidence_count=len(state.evidence),
                citation_verification_passed=True,
                evaluation={
                    "retrieval_strength": retrieval_output.max_score,
                    "provider_calls": state.provider_calls,
                },
            )
            state.final_response = result
            self._transition_terminal(state, WorkflowStatus.COMPLETED)
            return self._complete(state, result, started, tool_context.call_count)
        except Exception as exc:
            return self._safe_failure(
                state,
                started,
                outcome=AskOutcome.TEMPORARILY_UNAVAILABLE,
                category="specialist_failure",
                error_type=type(exc).__name__,
                tool_calls=state.tool_calls,
            )

    async def _run_agent(
        self,
        state: WorkflowState,
        agent: AgentName,
        operation: Callable[[], Awaitable[OutputT]],
        *,
        action_input: BaseModel,
        provider_call: bool,
    ) -> OutputT:
        if state.status.is_terminal:
            raise AgentWorkflowError(details={"reason": "workflow_already_terminal"})
        if state.active_agent is not None:
            raise AgentWorkflowError(details={"reason": "nested_agent_dispatch"})
        signature = (
            f"{agent.value}:{sha256(action_input.model_dump_json().encode('utf-8')).hexdigest()}"
        )
        if signature in state.agent_action_signatures:
            raise AgentLimitError(details={"limit": "repeated_agent_action"})
        state.agent_action_signatures.add(signature)
        spec = self.registry.get(agent)
        self._record_agent(state, agent)
        last_error: Exception | None = None
        for attempt in range(spec.maximum_retries + 1):
            started = perf_counter()
            self._audit(state, agent=agent, event="agent_started", success=True)
            logger.info(
                "agent_started",
                extra={"agent_name": agent.value, "attempt": attempt + 1},
            )
            if provider_call:
                if state.provider_calls >= self.maximum_provider_calls:
                    raise AgentLimitError(details={"limit": "provider_calls"})
                state.provider_calls += 1
            state.active_agent = agent
            try:
                output = await asyncio.wait_for(operation(), timeout=spec.timeout_seconds)
                validated = spec.output_schema.model_validate(output)
                self._audit(
                    state,
                    agent=agent,
                    event="agent_completed",
                    success=True,
                    duration_ms=(perf_counter() - started) * 1000,
                )
                logger.info(
                    "agent_completed",
                    extra={
                        "agent_name": agent.value,
                        "duration_ms": round((perf_counter() - started) * 1000, 2),
                    },
                )
                return validated  # type: ignore[return-value]
            except Exception as exc:
                last_error = exc
                self._audit(
                    state,
                    agent=agent,
                    event="agent_completed",
                    success=False,
                    duration_ms=(perf_counter() - started) * 1000,
                    failure="timeout" if isinstance(exc, TimeoutError) else "agent_failure",
                )
                if attempt >= spec.maximum_retries:
                    raise AgentWorkflowError(
                        details={"agent": agent.value, "failure": "bounded_execution"}
                    ) from exc
            finally:
                state.active_agent = None
        raise AgentWorkflowError() from last_error

    def _complete(
        self,
        state: WorkflowState,
        result: AskResult,
        started: float,
        tool_calls: int,
    ) -> AgenticAskResult:
        if not state.status.is_terminal:
            raise AgentWorkflowError(details={"reason": "missing_terminal_state"})
        duration = (perf_counter() - started) * 1000
        logger.info(
            "agent_workflow_completed",
            extra={
                "agent_count": len(state.agents_used),
                "tool_calls": tool_calls,
                "provider_calls": state.provider_calls,
                "citation_count": len(result.citations),
                "confidence": result.confidence.value,
                "requires_human_support": result.requires_human_support,
                "duration_ms": round(duration, 2),
                "terminal_state": state.status.value,
            },
        )
        return AgenticAskResult(
            result=result,
            workflow_mode=WorkflowMode.AGENTIC,
            agents_used=tuple(state.agents_used),
            tool_calls=tool_calls,
            provider_calls=state.provider_calls,
            duration_ms=duration,
            verification_passed=result.citation_verification_passed,
            terminal_state=state.status,
            audit_events=tuple(state.audit_events),
        )

    def _safe_failure(
        self,
        state: WorkflowState,
        started: float,
        *,
        outcome: AskOutcome,
        category: str,
        error_type: str | None = None,
        retrieved_count: int = 0,
        tool_calls: int = 0,
    ) -> AgenticAskResult:
        if outcome is AskOutcome.INSUFFICIENT_EVIDENCE:
            answer = (
                "I could not find enough consistent university policy evidence to answer this "
                "multi-part question safely. Please ask the relevant university team."
            )
            reason = "Reliable policy evidence was insufficient or conflicting."
        elif outcome is AskOutcome.VERIFICATION_FAILED:
            answer = (
                "The specialist workflow could not verify all policy findings and actions. "
                "Please consult the relevant university team."
            )
            reason = "The multi-agent result failed mandatory grounding verification."
        else:
            answer = (
                "The specialist workflow is temporarily unavailable. Please try again later or "
                "contact the relevant university support team."
            )
            reason = "The bounded specialist workflow could not be completed safely."
        result = AskResult(
            outcome=outcome,
            answer=answer,
            recommended_actions=(),
            citations=(),
            confidence=Confidence.LOW,
            limitations=(),
            requires_human_support=True,
            human_support_reason=reason,
            request_id=state.request_id,
            retrieved_count=retrieved_count,
            evidence_count=len(state.evidence),
            citation_verification_passed=False,
            evaluation={"retrieval_strength": 0.0, "provider_calls": state.provider_calls},
        )
        logger.info(
            "agent_workflow_escalated",
            extra={
                "failure_category": category,
                "error_type": error_type,
                "agent_count": len(state.agents_used),
                "tool_calls": tool_calls,
            },
        )
        self._transition_terminal(state, self._status_for_outcome(outcome))
        return self._complete(state, result, started, tool_calls)

    def _plan_once(
        self,
        state: WorkflowState,
        request: CoordinatorInput,
    ) -> CoordinatorDecision:
        if state.coordinator_calls >= 1:
            raise AgentLimitError(details={"limit": "coordinator_calls"})
        if state.active_agent is not None or state.status.is_terminal:
            raise AgentWorkflowError(details={"reason": "coordinator_reentry"})
        state.coordinator_calls += 1
        return self.coordinator.create_plan(request)

    def _verify_final_once(
        self,
        state: WorkflowState,
        *,
        support: StudentSupportOutput,
        analysis: PolicyAnalysisOutput,
        evidence: list[AgentEvidence],
        tool_invocations: list[ToolInvocationRecord],
    ) -> VerificationOutput:
        if state.final_verifier_calls >= 1:
            raise AgentLimitError(details={"limit": "final_verifier_calls"})
        if state.active_agent is not None or state.status.is_terminal:
            raise AgentWorkflowError(details={"reason": "verifier_reentry"})
        state.final_verifier_calls += 1
        return self.verifier.verify_final(
            support=support,
            analysis=analysis,
            evidence=evidence,
            tool_invocations=tool_invocations,
        )

    @staticmethod
    def _transition_terminal(state: WorkflowState, status: WorkflowStatus) -> None:
        if not status.is_terminal:
            raise AgentWorkflowError(details={"reason": "invalid_terminal_state"})
        if state.status.is_terminal:
            raise AgentWorkflowError(details={"reason": "terminal_state_is_irreversible"})
        state.status = status

    @staticmethod
    def _status_for_outcome(outcome: AskOutcome) -> WorkflowStatus:
        if outcome is AskOutcome.ANSWERED:
            return WorkflowStatus.COMPLETED
        if outcome in {
            AskOutcome.INSUFFICIENT_EVIDENCE,
            AskOutcome.UNSUPPORTED,
            AskOutcome.VERIFICATION_FAILED,
        }:
            return WorkflowStatus.ESCALATED
        return WorkflowStatus.FAILED

    @staticmethod
    def _record_agent(state: WorkflowState, agent: AgentName) -> None:
        if agent not in state.agents_used:
            state.agents_used.append(agent)

    @staticmethod
    def _audit(
        state: WorkflowState,
        *,
        agent: AgentName,
        event: str,
        success: bool,
        decision: str | None = None,
        duration_ms: float = 0.0,
        failure: str | None = None,
    ) -> None:
        state.audit_events.append(
            AgentAuditEvent(
                request_id=state.request_id,
                agent_name=agent,
                event_type=event,
                decision=decision,
                duration_ms=duration_ms,
                success=success,
                failure_category=failure,
            )
        )
