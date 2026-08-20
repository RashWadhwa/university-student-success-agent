"""Thin HTTP adapters for bounded reproducible evaluation."""

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_evaluation_runner
from backend.evaluation.runner import EvaluationRunner
from backend.schemas.evaluation import (
    EvaluationDatasetsResponse,
    EvaluationDatasetSummary,
    EvaluationRunRequest,
    EvaluationRunResponse,
)

router = APIRouter(prefix="/evaluations", tags=["evaluation"])


@router.get("/datasets", response_model=EvaluationDatasetsResponse)
async def datasets(
    runner: Annotated[EvaluationRunner, Depends(get_evaluation_runner)],
) -> EvaluationDatasetsResponse:
    cases = runner.dataset.load()
    return EvaluationDatasetsResponse(
        datasets=[
            EvaluationDatasetSummary(
                name=runner.dataset.name,
                case_count=len(cases),
                categories=sorted({case.category for case in cases}),
            )
        ]
    )


@router.post("/run", response_model=EvaluationRunResponse)
async def run_evaluation(
    request: EvaluationRunRequest,
    runner: Annotated[EvaluationRunner, Depends(get_evaluation_runner)],
) -> EvaluationRunResponse:
    result = await runner.run(workflow=request.workflow, case_ids=request.case_ids)
    return EvaluationRunResponse(result=result)
