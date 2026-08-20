"""Provider-independent Stage 7 evaluation contracts and implementations."""

from backend.evaluation.base import EvaluationProvider
from backend.evaluation.providers.mock_provider import MockEvaluationProvider

__all__ = ["EvaluationProvider", "MockEvaluationProvider"]
