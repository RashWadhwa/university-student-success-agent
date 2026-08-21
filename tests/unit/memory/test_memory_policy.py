"""Memory minimisation and consent schema tests."""

import pytest
from pydantic import ValidationError

from backend.schemas.memory import MemoryCreateRequest


def test_valid_distilled_memory_is_bounded() -> None:
    request = MemoryCreateRequest(
        memory_type="preference",
        fact="Prefers email reminders for agreed support actions.",
        consent=True,
        durable=True,
    )
    assert request.fact.startswith("Prefers")
    assert "user_id" not in request.model_fields


@pytest.mark.parametrize(
    "fact",
    [
        "User: hello Assistant: here is the answer",
        "### Conversation raw dialogue",
        "chat transcript containing a complete interaction",
    ],
)
def test_raw_conversation_storage_is_rejected(fact: str) -> None:
    with pytest.raises(ValidationError, match="transcript"):
        MemoryCreateRequest(memory_type="case_summary", fact=fact, consent=True, durable=True)


def test_oversized_memory_is_rejected() -> None:
    with pytest.raises(ValidationError):
        MemoryCreateRequest(memory_type="preference", fact="x" * 2001, consent=True, durable=True)


def test_transient_fact_is_explicitly_marked_non_durable() -> None:
    request = MemoryCreateRequest(
        memory_type="preference",
        fact="Temporary interaction detail.",
        consent=True,
        durable=False,
    )
    assert request.durable is False
