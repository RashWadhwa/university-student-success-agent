"""Safe errors for agent planning, authorization, and execution."""

from typing import Any

from backend.core.exceptions import ApplicationError


class AgentWorkflowError(ApplicationError):
    def __init__(
        self,
        *,
        code: str = "AGENT_WORKFLOW_FAILED",
        message: str = "The agent workflow could not be completed safely.",
        details: Any | None = None,
    ) -> None:
        super().__init__(code=code, message=message, status_code=503, details=details)


class AgentRegistryError(AgentWorkflowError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="AGENT_NOT_ALLOWED",
            message="The requested agent is not registered.",
            details=details,
        )


class ToolAuthorizationError(AgentWorkflowError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="TOOL_NOT_AUTHORISED",
            message="The tool invocation is not authorised.",
            details=details,
        )


class AgentLimitError(AgentWorkflowError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="AGENT_LIMIT_EXCEEDED",
            message="The agent workflow exceeded a configured safety limit.",
            details=details,
        )
