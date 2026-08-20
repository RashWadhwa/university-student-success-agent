"""Public Stage 7 evaluation API contracts."""

from typing import Literal

from pydantic import Field, field_validator

from backend.evaluation.models import EvaluationRunResult, EvaluationWorkflow
from backend.schemas.common import StrictModel


class EvaluationRunRequest(StrictModel):
    dataset: Literal["stage7-policy"] = "stage7-policy"
    workflow: EvaluationWorkflow = EvaluationWorkflow.BOTH
    case_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("case_ids")
    @classmethod
    def case_ids_must_be_unique(cls, values: list[str] | None) -> list[str] | None:
        if values is not None and len(values) != len(set(values)):
            raise ValueError("case_ids must be unique")
        return values


class EvaluationDatasetSummary(StrictModel):
    name: str
    case_count: int = Field(ge=1)
    categories: list[str]


class EvaluationDatasetsResponse(StrictModel):
    datasets: list[EvaluationDatasetSummary]


class EvaluationRunResponse(StrictModel):
    result: EvaluationRunResult
