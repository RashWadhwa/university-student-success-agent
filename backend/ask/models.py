"""Strict structured output requested from the language model."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from backend.schemas.common import StrictModel

_CitationId = Annotated[str, StringConstraints(pattern=r"^E[1-9][0-9]*$")]


class GeneratedPolicyFact(StrictModel):
    """A single university-policy claim; must be independently grounded."""

    fact: str = Field(min_length=1, max_length=500)
    citation_ids: list[_CitationId] = Field(default_factory=list, max_length=10)

    @field_validator("fact")
    @classmethod
    def strip_fact(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("fact must not be blank")
        return cleaned


class GeneratedAction(StrictModel):
    """A student-facing step, with optional supporting evidence.

    The model supplies content and any evidence references it relied on — nothing
    else. Whether an action is policy-backed or generic guidance is a backend
    classification decided after generation (see backend.ask.verification); the
    model never labels or self-classifies its own content.
    """

    priority: int = Field(ge=1, le=20)
    action: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)
    citation_ids: list[_CitationId] = Field(default_factory=list, max_length=10)

    @field_validator("action", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must not be blank")
        return cleaned


class GroundedAnswerOutput(StrictModel):
    """Model-authored content; classification, confidence, and citations remain

    application-controlled. The model never assigns a policy/practical label to
    its own actions — the backend deterministically classifies each action from
    its content after generation, so a security-relevant decision never rests
    on anything the model says about itself.
    """

    summary: str = Field(min_length=1, max_length=3000)
    policy_facts: list[GeneratedPolicyFact] = Field(default_factory=list, max_length=10)
    actions: list[GeneratedAction] = Field(default_factory=list, max_length=10)
    limitations: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    ] = Field(default_factory=list, max_length=10)
    confidence: Literal["high", "medium", "low"]
    requires_human_support: bool
    human_support_reason: str | None = Field(default=None, max_length=1000)

    @field_validator("summary")
    @classmethod
    def summary_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("summary must not be blank")
        return cleaned

    @field_validator("limitations")
    @classmethod
    def clean_limitations(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]
