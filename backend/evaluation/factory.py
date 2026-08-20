"""Configuration-driven factory for the replaceable Stage 7 judge."""

from backend.core.config import EvaluationProviderName, Settings
from backend.evaluation.base import EvaluationProvider
from backend.evaluation.errors import EvaluationConfigurationError
from backend.evaluation.providers.gemini_provider import GeminiEvaluationProvider
from backend.evaluation.providers.mock_provider import MockEvaluationProvider


def create_evaluation_provider(settings: Settings) -> EvaluationProvider:
    if settings.eval_provider is EvaluationProviderName.MOCK:
        return MockEvaluationProvider()
    if settings.eval_provider is EvaluationProviderName.GEMINI:
        return GeminiEvaluationProvider(settings)
    raise EvaluationConfigurationError(details={"provider": str(settings.eval_provider)})
