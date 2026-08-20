"""Fixed agent contracts and application-enforced capability registry."""

from dataclasses import dataclass

from pydantic import BaseModel

from backend.agents.errors import AgentLimitError, AgentRegistryError, ToolAuthorizationError
from backend.agents.models import (
    CoordinatorDecision,
    CoordinatorInput,
    PolicyAnalysisOutput,
    PolicyAnalystInput,
    RetrievalAgentInput,
    RetrievalAgentOutput,
    StudentSupportInput,
    StudentSupportOutput,
    VerificationOutput,
    VerifierInput,
)
from backend.agents.types import AgentName, ToolName, ToolPermission


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: AgentName
    responsibility: str
    allowed_tools: frozenset[ToolName]
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    timeout_seconds: float
    maximum_retries: int
    may_call_llm: bool
    may_access_retrieval: bool
    may_produce_user_text: bool


class AgentRegistry:
    """Resolve only statically registered agents and tool permissions."""

    def __init__(self, *, timeout_seconds: float, maximum_retries: int) -> None:
        if not 0 <= maximum_retries <= 3:
            raise AgentLimitError(details={"limit": "retries"})
        if not 0 < timeout_seconds <= 120:
            raise AgentLimitError(details={"limit": "timeout"})
        self._tool_permissions = {
            ToolName.SEARCH_KNOWLEDGE_BASE: ToolPermission.READ,
            ToolName.GET_DOCUMENT_SECTION: ToolPermission.READ,
            ToolName.FIND_STUDENT_SERVICE: ToolPermission.READ,
            ToolName.DRAFT_SUPPORT_EMAIL: ToolPermission.PREPARE,
        }
        self._agents = {
            AgentName.COORDINATOR: AgentSpec(
                name=AgentName.COORDINATOR,
                responsibility="Classify scope and create a bounded execution plan.",
                allowed_tools=frozenset(),
                input_schema=CoordinatorInput,
                output_schema=CoordinatorDecision,
                timeout_seconds=timeout_seconds,
                maximum_retries=0,
                may_call_llm=False,
                may_access_retrieval=False,
                may_produce_user_text=False,
            ),
            AgentName.RETRIEVAL: AgentSpec(
                name=AgentName.RETRIEVAL,
                responsibility="Retrieve bounded citation-ready policy evidence.",
                allowed_tools=frozenset(
                    {ToolName.SEARCH_KNOWLEDGE_BASE, ToolName.GET_DOCUMENT_SECTION}
                ),
                input_schema=RetrievalAgentInput,
                output_schema=RetrievalAgentOutput,
                timeout_seconds=timeout_seconds,
                maximum_retries=maximum_retries,
                may_call_llm=False,
                may_access_retrieval=True,
                may_produce_user_text=False,
            ),
            AgentName.POLICY_ANALYST: AgentSpec(
                name=AgentName.POLICY_ANALYST,
                responsibility="Extract cited policy facts from bounded evidence.",
                allowed_tools=frozenset({ToolName.GET_DOCUMENT_SECTION}),
                input_schema=PolicyAnalystInput,
                output_schema=PolicyAnalysisOutput,
                timeout_seconds=timeout_seconds,
                maximum_retries=maximum_retries,
                may_call_llm=True,
                may_access_retrieval=False,
                may_produce_user_text=False,
            ),
            AgentName.STUDENT_SUPPORT: AgentSpec(
                name=AgentName.STUDENT_SUPPORT,
                responsibility="Convert verified findings into bounded practical actions.",
                allowed_tools=frozenset(
                    {ToolName.FIND_STUDENT_SERVICE, ToolName.DRAFT_SUPPORT_EMAIL}
                ),
                input_schema=StudentSupportInput,
                output_schema=StudentSupportOutput,
                timeout_seconds=timeout_seconds,
                maximum_retries=maximum_retries,
                may_call_llm=True,
                may_access_retrieval=False,
                may_produce_user_text=True,
            ),
            AgentName.VERIFIER: AgentSpec(
                name=AgentName.VERIFIER,
                responsibility="Reject ungrounded, unsafe, or unauthorised workflow output.",
                allowed_tools=frozenset(),
                input_schema=VerifierInput,
                output_schema=VerificationOutput,
                timeout_seconds=timeout_seconds,
                maximum_retries=0,
                may_call_llm=False,
                may_access_retrieval=False,
                may_produce_user_text=False,
            ),
        }

    def get(self, agent: AgentName | str) -> AgentSpec:
        try:
            name = AgentName(agent)
            return self._agents[name]
        except (ValueError, KeyError) as exc:
            raise AgentRegistryError(details={"agent": "unknown"}) from exc

    def authorise_tool(
        self,
        *,
        agent: AgentName | str,
        tool: ToolName | str,
        permission: ToolPermission | str,
    ) -> AgentSpec:
        spec = self.get(agent)
        try:
            tool_name = ToolName(tool)
            permission_level = ToolPermission(permission)
        except ValueError as exc:
            raise ToolAuthorizationError(details={"reason": "unknown_capability"}) from exc
        if tool_name not in spec.allowed_tools:
            raise ToolAuthorizationError(
                details={"agent": spec.name.value, "tool": tool_name.value}
            )
        if permission_level is ToolPermission.EXECUTE:
            raise ToolAuthorizationError(details={"reason": "execute_not_enabled"})
        if self._tool_permissions.get(tool_name) is not permission_level:
            raise ToolAuthorizationError(details={"reason": "permission_mismatch"})
        return spec

    @property
    def names(self) -> tuple[AgentName, ...]:
        return tuple(self._agents)
