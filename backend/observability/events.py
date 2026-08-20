"""Central safe event mapping for public workflow results."""

from backend.agents.types import AgenticAskResult
from backend.ask.types import AskResult
from backend.observability.base import ObservabilityService


async def record_ask_started(
    observability: ObservabilityService,
    *,
    request_id: str,
    workflow_mode: str,
    input_length: int,
) -> str | None:
    return await observability.record_event(
        event="ask.request.started",
        request_id=request_id,
        metadata={"workflow_mode": workflow_mode, "input_length": input_length},
    )


async def record_ask_result(
    observability: ObservabilityService,
    result: AskResult | AgenticAskResult,
) -> str | None:
    if isinstance(result, AgenticAskResult):
        answer = result.result
        metadata = {
            "workflow_mode": result.workflow_mode.value,
            "latency_ms": round(result.duration_ms, 2),
            "retrieval_count": answer.retrieved_count,
            "citation_count": len(answer.citations),
            "agent_names": [agent.value for agent in result.agents_used],
            "tool_names": ["search_knowledge_base"] if result.tool_calls else [],
            "tool_calls": result.tool_calls,
            "provider_calls": result.provider_calls,
            "confidence": answer.confidence.value,
            "terminal_state": result.terminal_state.value,
            "success": result.verification_passed,
            "outcome": answer.outcome.value,
        }
    else:
        answer = result
        metadata = {
            "workflow_mode": "baseline",
            "retrieval_count": answer.retrieved_count,
            "citation_count": len(answer.citations),
            "confidence": answer.confidence.value,
            "success": answer.citation_verification_passed,
            "outcome": answer.outcome.value,
            "provider_calls": int(answer.evaluation.get("provider_calls", 0)),
        }
    await observability.record_event(
        event="retrieval.completed",
        request_id=answer.request_id,
        metadata={
            "workflow_mode": metadata["workflow_mode"],
            "retrieval_count": answer.retrieved_count,
            "citation_count": len(answer.citations),
            "success": answer.evidence_count > 0,
        },
    )
    if int(metadata.get("provider_calls", 0)) > 0:
        await observability.record_event(
            event="embedding.completed",
            request_id=answer.request_id,
            metadata={
                "workflow_mode": metadata["workflow_mode"],
                "provider_calls": 1,
                "success": True,
            },
        )
    await observability.record_event(
        event="generation.completed",
        request_id=answer.request_id,
        metadata={
            "workflow_mode": metadata["workflow_mode"],
            "provider_calls": int(metadata.get("provider_calls", 0)),
            "success": answer.outcome.value == "answered",
            "outcome": answer.outcome.value,
        },
    )
    if isinstance(result, AgenticAskResult):
        for agent in result.agents_used:
            await observability.record_event(
                event="agent.completed",
                request_id=answer.request_id,
                metadata={
                    "workflow_mode": result.workflow_mode.value,
                    "agent_names": [agent.value],
                    "success": True,
                },
            )
        if result.tool_calls:
            await observability.record_event(
                event="tool.completed",
                request_id=answer.request_id,
                metadata={
                    "workflow_mode": result.workflow_mode.value,
                    "tool_names": ["search_knowledge_base"],
                    "tool_calls": result.tool_calls,
                    "success": True,
                },
            )
    await observability.record_event(
        event="verification.completed",
        request_id=answer.request_id,
        metadata={
            "workflow_mode": metadata["workflow_mode"],
            "citation_count": len(answer.citations),
            "success": answer.citation_verification_passed,
        },
    )
    return await observability.record_event(
        event="ask.request.completed",
        request_id=answer.request_id,
        metadata=metadata,
    )
