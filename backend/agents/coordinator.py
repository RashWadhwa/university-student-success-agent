"""Deterministic coordinator producing bounded typed execution plans."""

import re

from backend.agents.errors import AgentLimitError, AgentWorkflowError
from backend.agents.models import (
    AgentTask,
    CoordinatorDecision,
    CoordinatorInput,
    ExecutionPlan,
)
from backend.agents.registry import AgentRegistry
from backend.agents.types import AgentName, PlanComplexity, RequestIntent
from backend.ask.scope import assess_scope

_INTENT_PATTERNS = {
    RequestIntent.ASSESSMENT_ISSUE: re.compile(
        r"\b(assessment|exam|submission|deadline|missed|late)\b", re.I
    ),
    RequestIntent.EXTENSION: re.compile(r"\bextensions?\b", re.I),
    RequestIntent.MITIGATING_CIRCUMSTANCES: re.compile(
        r"\b(mitigating|extenuating|ill(?:ness)?|circumstances?)\b", re.I
    ),
    RequestIntent.REASSESSMENT: re.compile(r"\b(reassessment|resit|retake)\b", re.I),
    RequestIntent.ACADEMIC_APPEAL: re.compile(r"\b(academic\s+appeal|appeal)\b", re.I),
}


class Coordinator:
    """Choose baseline delegation or one fixed specialist sequence."""

    def __init__(self, *, registry: AgentRegistry, maximum_tasks: int) -> None:
        if not 1 <= maximum_tasks <= 10:
            raise AgentLimitError(details={"limit": "tasks"})
        self.registry = registry
        self.maximum_tasks = maximum_tasks

    def create_plan(self, request: CoordinatorInput) -> CoordinatorDecision:
        scope = assess_scope(request.question)
        if not scope.supported:
            return CoordinatorDecision(
                scope_supported=False,
                scope_reason=scope.reason,
            )
        intents = [
            intent
            for intent, pattern in _INTENT_PATTERNS.items()
            if pattern.search(request.question)
        ]
        if not intents:
            intents = [RequestIntent.ASSESSMENT_ISSUE]
        intent_name = "_with_".join(intent.value for intent in intents)
        if len(intents) == 1:
            plan = ExecutionPlan(
                intent=intent_name,
                intents=intents,
                complexity=PlanComplexity.SINGLE_STEP,
                tasks=[],
                use_baseline=True,
                requires_verification=True,
                requires_human_support=scope.requires_individual_decision,
            )
        else:
            objective = "Analyse the applicable rules for " + ", ".join(
                intent.value.replace("_", " ") for intent in intents
            )
            plan = ExecutionPlan(
                intent=intent_name,
                intents=intents,
                complexity=PlanComplexity.MULTI_STEP,
                tasks=[
                    AgentTask(
                        agent=AgentName.RETRIEVAL,
                        objective=f"Retrieve evidence for {objective}.",
                    ),
                    AgentTask(
                        agent=AgentName.POLICY_ANALYST,
                        objective=f"Identify cited policy requirements for {objective}.",
                    ),
                    AgentTask(
                        agent=AgentName.STUDENT_SUPPORT,
                        objective="Convert verified findings into safe prioritised actions.",
                    ),
                    AgentTask(
                        agent=AgentName.VERIFIER,
                        objective="Verify grounding, permissions, citations, and safety.",
                    ),
                ],
                use_baseline=False,
                requires_verification=True,
                requires_human_support=scope.requires_individual_decision,
            )
        self.validate_plan(plan)
        return CoordinatorDecision(scope_supported=True, plan=plan)

    def validate_plan(self, plan: ExecutionPlan) -> None:
        if len(plan.tasks) > self.maximum_tasks:
            raise AgentLimitError(details={"limit": "tasks"})
        if plan.use_baseline:
            return
        names = [task.agent for task in plan.tasks]
        allowed_sequence = [
            AgentName.RETRIEVAL,
            AgentName.POLICY_ANALYST,
            AgentName.STUDENT_SUPPORT,
            AgentName.VERIFIER,
        ]
        if names != allowed_sequence:
            raise AgentWorkflowError(
                code="AGENT_PLAN_INVALID",
                message="The coordinator returned an invalid execution plan.",
            )
        for name in names:
            self.registry.get(name)
