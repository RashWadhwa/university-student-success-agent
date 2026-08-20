"""Narrow retrieval, policy-analysis, and student-support specialists."""

import json

from backend.agents.models import (
    PolicyAnalysisOutput,
    PolicyAnalystInput,
    RetrievalAgentInput,
    RetrievalAgentOutput,
    StudentSupportInput,
    StudentSupportOutput,
)
from backend.agents.prompts import (
    POLICY_ANALYST_SYSTEM_PROMPT,
    STUDENT_SUPPORT_SYSTEM_PROMPT,
)
from backend.agents.tools import SearchKnowledgeBaseInput, ToolContext, ToolExecutor
from backend.agents.types import AgentName, ToolName
from backend.llm.base import GenerationOptions, LLMProvider


class RetrievalSpecialist:
    def __init__(self, *, tools: ToolExecutor) -> None:
        self.tools = tools

    async def execute(
        self,
        request: RetrievalAgentInput,
        context: ToolContext,
    ) -> RetrievalAgentOutput:
        output = await self.tools.invoke(
            agent=AgentName.RETRIEVAL,
            tool=ToolName.SEARCH_KNOWLEDGE_BASE,
            arguments=SearchKnowledgeBaseInput(
                query=request.query,
                top_k=request.top_k,
                filters=request.filters,
            ).model_dump(mode="json"),
            context=context,
        )
        return RetrievalAgentOutput.model_validate(output)


class PolicyAnalyst:
    def __init__(self, *, provider: LLMProvider) -> None:
        self.provider = provider

    async def execute(self, request: PolicyAnalystInput) -> PolicyAnalysisOutput:
        evidence_payload = [
            {
                "citation_id": item.citation_id,
                "title": item.title,
                "section": item.section,
                "page": item.page,
                "version": item.version,
                "effective_date": (
                    item.effective_date.isoformat() if item.effective_date else None
                ),
                "content": item.content,
            }
            for item in request.evidence
        ]
        prompt = (
            f"OBJECTIVE:\n{request.objective}\n\n"
            "BEGIN_UNTRUSTED_EVIDENCE_JSON\n"
            f"{json.dumps(evidence_payload, ensure_ascii=False)}\n"
            "END_UNTRUSTED_EVIDENCE_JSON"
        )
        result = await self.provider.generate_structured(
            system_prompt=POLICY_ANALYST_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_model=PolicyAnalysisOutput,
            options=GenerationOptions(),
        )
        return result.output


class StudentSupportSpecialist:
    def __init__(self, *, provider: LLMProvider) -> None:
        self.provider = provider

    async def execute(self, request: StudentSupportInput) -> StudentSupportOutput:
        prompt = (
            f"SAFE_INTENT_LABEL: {request.intent}\n"
            f"INDIVIDUAL_DECISION_REQUIRED: {request.requires_individual_decision}\n\n"
            "BEGIN_UNTRUSTED_VERIFIED_POLICY_JSON\n"
            f"{request.policy_analysis.model_dump_json()}\n"
            "END_UNTRUSTED_VERIFIED_POLICY_JSON"
        )
        result = await self.provider.generate_structured(
            system_prompt=STUDENT_SUPPORT_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_model=StudentSupportOutput,
            options=GenerationOptions(),
        )
        return result.output
