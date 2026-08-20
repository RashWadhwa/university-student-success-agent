"""Safe evaluator metadata boundary for future Langfuse observations."""

from backend.evaluation.base import EvaluationProvider


def safe_evaluator_trace_metadata(provider: EvaluationProvider) -> dict[str, str]:
    """Return the only evaluator fields permitted on Langfuse traces."""

    return {
        "provider": provider.name,
        "model": provider.model,
    }
