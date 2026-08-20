"""Safe auxiliary system status for the Streamlit System page."""

from fastapi import APIRouter, Request

from backend.database.manager import DatabaseManager, DatabaseReadiness
from backend.evaluation.base import EvaluationProvider
from backend.llm.base import LLMProvider
from backend.observability.base import ObservabilityService
from backend.schemas.system import ComponentStatus, SystemStatusResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusResponse)
async def system_status(request: Request) -> SystemStatusResponse:
    database: DatabaseManager | None = getattr(request.app.state, "database_manager", None)
    readiness = (
        await database.check_readiness()
        if database is not None
        else DatabaseReadiness(database=False, pgvector=False)
    )
    llm: LLMProvider | None = getattr(request.app.state, "llm_provider", None)
    evaluator: EvaluationProvider | None = getattr(request.app.state, "evaluation_provider", None)
    observability: ObservabilityService | None = getattr(request.app.state, "observability", None)
    return SystemStatusResponse(
        fastapi=ComponentStatus(status="operational"),
        database=ComponentStatus(status="operational" if readiness.database else "unavailable"),
        pgvector=ComponentStatus(status="operational" if readiness.pgvector else "unavailable"),
        primary_llm=ComponentStatus(
            status="operational" if llm is not None and llm.is_configured else "unconfigured",
            provider=llm.name if llm is not None else None,
            model=llm.model if llm is not None else None,
        ),
        langfuse=ComponentStatus(
            status=(
                "operational" if observability is not None and observability.enabled else "disabled"
            ),
            provider=observability.name if observability is not None else None,
        ),
        evaluation=ComponentStatus(
            status=(
                "operational"
                if evaluator is not None and evaluator.is_configured
                else "unconfigured"
            ),
            provider=evaluator.name if evaluator is not None else None,
            model=evaluator.model if evaluator is not None else None,
        ),
    )
