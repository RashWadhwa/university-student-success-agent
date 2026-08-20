"""Provider-independent contracts and result types for language models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    """Provider-neutral controls for a text or structured generation call."""

    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Normalised token usage returned by an LLM provider."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMResult(Generic[StructuredOutputT]):
    """Normalised model result with metadata required for traces and evals."""

    output: StructuredOutputT
    provider: str
    model: str
    latency_ms: float
    usage: TokenUsage
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class TextResult:
    """Normalised unstructured text result."""

    output: str
    provider: str
    model: str
    latency_ms: float
    usage: TokenUsage
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Normalised embedding result."""

    embeddings: list[list[float]]
    provider: str
    model: str
    latency_ms: float
    usage: TokenUsage
    provider_request_id: str | None = None


class LLMProvider(ABC):
    """Contract implemented by every model provider used by the application."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the stable provider identifier."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the configured generation model identifier."""

    @property
    @abstractmethod
    def embedding_model(self) -> str:
        """Return the configured embedding model identifier."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return whether local provider configuration is complete."""

    @abstractmethod
    async def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        options: GenerationOptions | None = None,
    ) -> TextResult:
        """Generate unstructured text."""

    @abstractmethod
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
        options: GenerationOptions | None = None,
    ) -> LLMResult[StructuredOutputT]:
        """Generate output validated against a Pydantic model."""

    @abstractmethod
    async def create_embeddings(self, texts: list[str]) -> EmbeddingResult:
        """Create embeddings in the same order as the supplied texts."""

    @abstractmethod
    async def close(self) -> None:
        """Release provider-owned network resources."""
