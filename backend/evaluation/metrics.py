"""Deterministic evaluation metrics kept separate from semantic judge scores."""

from collections.abc import Iterable

from backend.evaluation.models import DeterministicScores, EvaluationCase
from backend.rag.evaluation import (
    hit_rate_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def deterministic_scores(
    *,
    case: EvaluationCase,
    retrieved_titles: list[str],
    citations_valid: bool,
    requires_human_support: bool,
    confidence: str,
    structured_output_valid: bool,
    agents_used: Iterable[str] = (),
    tool_calls: int = 0,
    workflow_mode: str,
) -> DeterministicScores:
    relevant = {title.casefold() for title in case.relevant_titles}
    retrieved = [title.casefold() for title in retrieved_titles]
    k = max(1, len(retrieved))
    if relevant:
        recall = recall_at_k(retrieved, relevant, k)
        precision = precision_at_k(retrieved, relevant, k)
        reciprocal = reciprocal_rank(retrieved, relevant)
        hit_rate = hit_rate_at_k(retrieved, relevant, k)
    else:
        no_retrieval = float(not retrieved)
        recall = precision = reciprocal = hit_rate = no_retrieval
    expected_agents = set(case.expected_agents)
    actual_agents = set(agents_used)
    agent_routing = None
    tool_selection = None
    if workflow_mode == "agentic":
        agent_routing = float(not expected_agents or expected_agents <= actual_agents)
        tool_selection = float(tool_calls >= case.minimum_tool_calls)
    return DeterministicScores(
        recall_at_k=recall,
        precision_at_k=precision,
        reciprocal_rank=reciprocal,
        hit_rate=hit_rate,
        citation_validity=float(citations_valid),
        escalation_correctness=float(requires_human_support == case.expected_escalation),
        structured_output_validity=float(structured_output_valid),
        confidence_calibration=(
            1.0
            if case.expected_confidence is None
            else float(confidence == case.expected_confidence)
        ),
        agent_routing=agent_routing,
        tool_selection=tool_selection,
    )
