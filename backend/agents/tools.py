"""Typed, permissioned READ/PREPARE tools with no external side effects."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from time import perf_counter
from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from backend.agents.errors import AgentLimitError, ToolAuthorizationError
from backend.agents.models import (
    AgentAuditEvent,
    AgentEvidence,
    RetrievalAgentOutput,
    ToolInvocationRecord,
)
from backend.agents.registry import AgentRegistry
from backend.agents.types import AgentName, ToolName, ToolPermission
from backend.ask.evidence import assess_evidence
from backend.rag.retrieval import RetrievalService
from backend.schemas.common import StrictModel
from backend.schemas.retrieval import RetrievalFilters

logger = logging.getLogger(__name__)


class SearchKnowledgeBaseInput(StrictModel):
    query: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(ge=1, le=100)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class GetDocumentSectionInput(StrictModel):
    citation_id: str = Field(pattern=r"^E[1-9][0-9]*$")


class GetDocumentSectionOutput(StrictModel):
    evidence: AgentEvidence


class StudentService(StrEnum):
    ACADEMIC_ADVICE = "academic_advice"
    ASSESSMENT_SUPPORT = "assessment_support"
    APPEALS_TEAM = "appeals_team"
    WELLBEING = "wellbeing"


class FindStudentServiceInput(StrictModel):
    service: StudentService


class FindStudentServiceOutput(StrictModel):
    service: StudentService
    guidance: str = Field(min_length=1, max_length=500)


class DraftSupportEmailInput(StrictModel):
    purpose: str = Field(min_length=1, max_length=300)
    facts: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    ] = Field(default_factory=list, max_length=10)


class DraftSupportEmailOutput(StrictModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    status: str = Field(default="draft_only", pattern=r"^draft_only$")


@dataclass(slots=True)
class ToolContext:
    request_id: str
    maximum_calls: int
    evidence: dict[str, AgentEvidence] = field(default_factory=dict)
    invocations: list[ToolInvocationRecord] = field(default_factory=list)
    audit_events: list[AgentAuditEvent] = field(default_factory=list)
    call_count: int = 0
    action_signatures: set[str] = field(default_factory=set)


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[BaseModel]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: ToolName
    permission: ToolPermission
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    handler: ToolHandler


class ToolExecutor:
    """Validate and authorize every invocation in application code."""

    def __init__(self, *, registry: AgentRegistry, definitions: list[ToolDefinition]) -> None:
        self.registry = registry
        self._definitions = {definition.name: definition for definition in definitions}

    async def invoke(
        self,
        *,
        agent: AgentName | str,
        tool: ToolName | str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> BaseModel:
        started = perf_counter()
        try:
            tool_name = ToolName(tool)
            definition = self._definitions[tool_name]
        except (ValueError, KeyError) as exc:
            self._audit_rejection(context, agent, failure="unknown_tool")
            raise ToolAuthorizationError(details={"reason": "unknown_tool"}) from exc
        try:
            spec = self.registry.authorise_tool(
                agent=agent,
                tool=tool_name,
                permission=definition.permission,
            )
        except ToolAuthorizationError:
            self._audit_rejection(context, agent, tool=tool_name, failure="not_authorised")
            safe_agent = agent.value if isinstance(agent, AgentName) else "unknown"
            logger.info(
                "tool_rejected",
                extra={"agent_name": safe_agent, "tool_name": tool_name.value},
            )
            raise
        if context.call_count >= context.maximum_calls:
            self._audit_rejection(context, spec.name, tool=tool_name, failure="call_limit")
            raise AgentLimitError(details={"limit": "tool_calls"})

        try:
            validated_input = definition.input_schema.model_validate(arguments)
        except Exception:
            self._audit_rejection(
                context,
                spec.name,
                tool=tool_name,
                failure="invalid_arguments",
            )
            raise
        signature = (
            f"{spec.name.value}:{tool_name.value}:"
            f"{sha256(validated_input.model_dump_json().encode('utf-8')).hexdigest()}"
        )
        if signature in context.action_signatures:
            self._audit_rejection(
                context,
                spec.name,
                tool=tool_name,
                failure="repeated_action",
            )
            raise AgentLimitError(details={"limit": "repeated_tool_action"})
        context.action_signatures.add(signature)
        context.call_count += 1
        try:
            raw_output = await definition.handler(validated_input, context)
            output = definition.output_schema.model_validate(raw_output)
        except Exception:
            context.invocations.append(
                ToolInvocationRecord(
                    agent_name=spec.name,
                    tool_name=tool_name,
                    permission_level=definition.permission,
                    authorised=True,
                    success=False,
                )
            )
            context.audit_events.append(
                AgentAuditEvent(
                    request_id=context.request_id,
                    agent_name=spec.name,
                    event_type="tool_completed",
                    tool_name=tool_name,
                    permission_level=definition.permission,
                    decision="allowed",
                    duration_ms=(perf_counter() - started) * 1000,
                    success=False,
                    failure_category="tool_failure",
                )
            )
            raise

        context.invocations.append(
            ToolInvocationRecord(
                agent_name=spec.name,
                tool_name=tool_name,
                permission_level=definition.permission,
                authorised=True,
                success=True,
            )
        )
        context.audit_events.append(
            AgentAuditEvent(
                request_id=context.request_id,
                agent_name=spec.name,
                event_type="tool_completed",
                tool_name=tool_name,
                permission_level=definition.permission,
                decision="allowed",
                duration_ms=(perf_counter() - started) * 1000,
                success=True,
            )
        )
        logger.info(
            "tool_authorised",
            extra={
                "agent_name": spec.name.value,
                "tool_name": tool_name.value,
                "permission_level": definition.permission.value,
            },
        )
        return output

    @staticmethod
    def _audit_rejection(
        context: ToolContext,
        agent: AgentName | str,
        *,
        tool: ToolName | None = None,
        failure: str,
    ) -> None:
        try:
            agent_name = AgentName(agent)
        except ValueError:
            agent_name = AgentName.COORDINATOR
        context.audit_events.append(
            AgentAuditEvent(
                request_id=context.request_id,
                agent_name=agent_name,
                event_type="tool_rejected",
                tool_name=tool,
                decision="rejected",
                success=False,
                failure_category=failure,
            )
        )


def build_tool_executor(
    *,
    registry: AgentRegistry,
    retrieval: RetrievalService,
    minimum_evidence_count: int,
    minimum_retrieval_score: float,
    maximum_evidence_items: int,
    evidence_max_chars_per_chunk: int,
) -> ToolExecutor:
    async def search_handler(
        payload: BaseModel,
        context: ToolContext,
    ) -> BaseModel:
        request = SearchKnowledgeBaseInput.model_validate(payload)
        results = await retrieval.search(
            query=request.query,
            top_k=min(request.top_k, maximum_evidence_items),
            filters=request.filters.to_domain(),
            minimum_score=minimum_retrieval_score,
            prefer_recent=True,
        )
        assessment = assess_evidence(
            results,
            question=request.query,
            minimum_count=minimum_evidence_count,
            minimum_score=minimum_retrieval_score,
            maximum_chunks=maximum_evidence_items,
        )
        evidence = [
            AgentEvidence.from_domain(
                item,
                maximum_content_chars=evidence_max_chars_per_chunk,
            )
            for item in assessment.evidence
        ]
        context.evidence = {item.citation_id: item for item in evidence}
        return RetrievalAgentOutput(
            evidence=evidence,
            retrieved_count=len(results),
            sufficient=assessment.sufficient,
            conflicting=assessment.conflicting,
            reasons=list(assessment.reasons),
            max_score=assessment.max_score,
            older_versions_omitted=assessment.older_versions_omitted,
        )

    async def section_handler(payload: BaseModel, context: ToolContext) -> BaseModel:
        request = GetDocumentSectionInput.model_validate(payload)
        evidence = context.evidence.get(request.citation_id)
        if evidence is None:
            raise ToolAuthorizationError(details={"reason": "evidence_outside_request"})
        return GetDocumentSectionOutput(evidence=evidence)

    async def service_handler(payload: BaseModel, context: ToolContext) -> BaseModel:
        del context
        request = FindStudentServiceInput.model_validate(payload)
        labels = {
            StudentService.ACADEMIC_ADVICE: "Contact your university academic advice team.",
            StudentService.ASSESSMENT_SUPPORT: "Contact the university assessment support team.",
            StudentService.APPEALS_TEAM: "Contact the university team responsible for appeals.",
            StudentService.WELLBEING: "Consider contacting university wellbeing support.",
        }
        return FindStudentServiceOutput(service=request.service, guidance=labels[request.service])

    async def draft_handler(payload: BaseModel, context: ToolContext) -> BaseModel:
        del context
        request = DraftSupportEmailInput.model_validate(payload)
        facts = "\n".join(f"- {fact[:300]}" for fact in request.facts)
        body = (
            "Hello,\n\n"
            f"I am writing about {request.purpose}.\n"
            f"{facts}\n\n"
            "Please could you advise me on the applicable university process?\n\nThank you."
        )
        return DraftSupportEmailOutput(
            subject=f"Request for guidance: {request.purpose}",
            body=body,
        )

    return ToolExecutor(
        registry=registry,
        definitions=[
            ToolDefinition(
                name=ToolName.SEARCH_KNOWLEDGE_BASE,
                permission=ToolPermission.READ,
                input_schema=SearchKnowledgeBaseInput,
                output_schema=RetrievalAgentOutput,
                handler=search_handler,
            ),
            ToolDefinition(
                name=ToolName.GET_DOCUMENT_SECTION,
                permission=ToolPermission.READ,
                input_schema=GetDocumentSectionInput,
                output_schema=GetDocumentSectionOutput,
                handler=section_handler,
            ),
            ToolDefinition(
                name=ToolName.FIND_STUDENT_SERVICE,
                permission=ToolPermission.READ,
                input_schema=FindStudentServiceInput,
                output_schema=FindStudentServiceOutput,
                handler=service_handler,
            ),
            ToolDefinition(
                name=ToolName.DRAFT_SUPPORT_EMAIL,
                permission=ToolPermission.PREPARE,
                input_schema=DraftSupportEmailInput,
                output_schema=DraftSupportEmailOutput,
                handler=draft_handler,
            ),
        ],
    )
