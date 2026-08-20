"""Public schemas for the controlled agentic ask workflow."""

from pydantic import Field

from backend.agents.types import AgenticAskResult, AgentName, WorkflowMode, WorkflowStatus
from backend.schemas.ask import AskResponse
from backend.schemas.common import StrictModel


class AgenticWorkflowMetadata(StrictModel):
    """Safe comparison data; prompts, evidence bodies, and internal state are excluded."""

    workflow_mode: WorkflowMode
    agents_used: list[AgentName] = Field(max_length=5)
    tool_calls: int = Field(ge=0)
    retrieval_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    confidence: str
    requires_human_support: bool
    duration_ms: float = Field(ge=0.0)
    provider_calls: int = Field(ge=0)
    verification_passed: bool
    terminal_state: WorkflowStatus


class AgenticAskResponse(AskResponse):
    workflow: AgenticWorkflowMetadata

    @classmethod
    def from_result(cls, result: AgenticAskResult) -> "AgenticAskResponse":
        baseline = AskResponse.from_result(result.result)
        return cls(
            **baseline.model_dump(),
            workflow=AgenticWorkflowMetadata(
                workflow_mode=result.workflow_mode,
                agents_used=list(result.agents_used),
                tool_calls=result.tool_calls,
                retrieval_count=result.result.retrieved_count,
                citation_count=len(result.result.citations),
                confidence=result.result.confidence.value,
                requires_human_support=result.result.requires_human_support,
                duration_ms=result.duration_ms,
                provider_calls=result.provider_calls,
                verification_passed=result.verification_passed,
                terminal_state=result.terminal_state,
            ),
        )
