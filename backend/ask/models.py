"""Strict structured output requested from the language model."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from backend.schemas.common import StrictModel


class GeneratedCitation(StrictModel):
    citation_id: str = Field(pattern=r"^E[1-9][0-9]*$")


class GeneratedAction(StrictModel):
    priority: int = Field(ge=1, le=20)
    action: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)
    basis: Literal["policy", "practical"]
    citation_ids: list[Annotated[str, StringConstraints(pattern=r"^E[1-9][0-9]*$")]] = Field(
        default_factory=list, max_length=10
    )

    @field_validator("action", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class GroundedAnswerOutput(StrictModel):
    """Model-authored content; confidence and citations remain application-controlled."""

    answer: str = Field(min_length=1, max_length=5000)
    recommended_actions: list[GeneratedAction] = Field(default_factory=list, max_length=10)
    citations: list[GeneratedCitation] = Field(max_length=20)
    limitations: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    ] = Field(default_factory=list, max_length=10)
    confidence: Literal["high", "medium", "low"]
    requires_human_support: bool
    human_support_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("answer must not be blank")
        return cleaned

    @field_validator("limitations")
    @classmethod
    def clean_limitations(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]
