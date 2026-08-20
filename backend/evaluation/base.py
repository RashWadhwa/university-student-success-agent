"""Provider-independent contract for Stage 7 LLM-as-judge evaluation."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.evaluation.models import EvaluationInput, EvaluationOutput


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    output: EvaluationOutput
    provider: str
    model: str
    latency_ms: float
    provider_request_id: str | None = None


class EvaluationProvider(ABC):
    """Replaceable judge contract, independent of the generation provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable evaluator provider name."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the configured evaluator model name."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return whether the provider has the required local configuration."""

    @abstractmethod
    async def evaluate(self, request: EvaluationInput) -> EvaluationResult:
        """Return a validated multidimensional evaluation."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider-owned resources."""
