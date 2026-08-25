"""FastAPI application factory and ASGI entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.coordinator import Coordinator
from backend.agents.registry import AgentRegistry
from backend.agents.service import AgenticAskService
from backend.agents.specialists import (
    PolicyAnalyst,
    RetrievalSpecialist,
    StudentSupportSpecialist,
)
from backend.agents.tools import build_tool_executor
from backend.agents.verification import WorkflowVerifier
from backend.api.router import service_router, v1_router
from backend.ask.service import AskService
from backend.audit.service import AuditService
from backend.auth.identity_service import IdentityService
from backend.auth.service import AuthenticationService
from backend.auth.supabase_provider import SupabaseAuthProvider
from backend.core.config import Settings, get_settings
from backend.core.exceptions import register_exception_handlers
from backend.core.logging import configure_logging
from backend.core.middleware import RequestContextMiddleware
from backend.database.manager import DatabaseManager
from backend.documents.manager import DocumentManager
from backend.evaluation.base import EvaluationProvider
from backend.evaluation.dataset import EvaluationDataset
from backend.evaluation.errors import EvaluationError
from backend.evaluation.factory import create_evaluation_provider
from backend.evaluation.runner import EvaluationRunner
from backend.llm.base import LLMProvider
from backend.llm.errors import LLMConfigurationError
from backend.llm.factory import create_llm_provider
from backend.memory.service import MemoryService
from backend.observability.base import ObservabilityService
from backend.observability.factory import create_observability
from backend.rag.indexing import IndexingService
from backend.rag.retrieval import RetrievalService
from backend.security.middleware import SecurityMiddleware
from backend.security.rate_limit import RateLimitService

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    llm_provider: LLMProvider | None = None,
    document_manager: DocumentManager | None = None,
    database_manager: DatabaseManager | None = None,
    evaluation_provider: EvaluationProvider | None = None,
    observability: ObservabilityService | None = None,
) -> FastAPI:
    """Create and configure a FastAPI application instance."""

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.ready = False
        app.state.started_at = datetime.now(UTC)
        app.state.llm_provider = None
        app.state.llm_provider_error = None
        app.state.observability = observability or create_observability(resolved_settings)
        app.state.evaluation_provider = None
        app.state.evaluation_provider_error = None
        app.state.evaluation_runner = None
        app.state.database_manager = database_manager or DatabaseManager(
            resolved_settings.database_url.get_secret_value(),
            pool_size=resolved_settings.database_pool_size,
            max_overflow=resolved_settings.database_max_overflow,
            pool_timeout=resolved_settings.database_pool_timeout,
            readiness_timeout=resolved_settings.database_readiness_timeout,
        )
        app.state.auth_service = AuthenticationService(resolved_settings)
        app.state.memory_service = MemoryService(app.state.database_manager, resolved_settings)
        app.state.audit_service = AuditService(
            app.state.database_manager,
            retention_days=resolved_settings.audit_retention_days,
            enabled=resolved_settings.environment.value != "testing",
        )
        app.state.identity_service = None
        if (
            resolved_settings.supabase_auth_url is not None
            and resolved_settings.supabase_anon_key is not None
        ):
            app.state.identity_service = IdentityService(
                SupabaseAuthProvider(
                    auth_url=resolved_settings.supabase_auth_url,
                    anon_key=resolved_settings.supabase_anon_key.get_secret_value(),
                    service_role_key=(
                        resolved_settings.supabase_service_role_key.get_secret_value()
                        if resolved_settings.supabase_service_role_key is not None
                        else None
                    ),
                ),
                default_tenant_id=resolved_settings.default_tenant_id,
                audit_service=app.state.audit_service,
            )
        app.state.rate_limit_service = RateLimitService(
            app.state.database_manager, resolved_settings
        )
        app.state.indexing_service = None
        app.state.retrieval_service = None
        app.state.ask_service = None
        app.state.agentic_ask_service = None
        app.state.document_manager = document_manager or DocumentManager(
            storage_path=resolved_settings.document_storage_path,
            max_file_size_bytes=resolved_settings.max_document_size_bytes,
            chunk_size=resolved_settings.chunk_size,
            chunk_overlap=resolved_settings.chunk_overlap,
        )
        logger.info(
            "Application starting",
            extra={
                "service": resolved_settings.app_name,
                "version": resolved_settings.app_version,
                "environment": resolved_settings.environment.value,
                "llm_provider": resolved_settings.llm_provider.value,
                "observability": app.state.observability.name,
            },
        )

        active_provider: LLMProvider | None = None
        try:
            active_provider = llm_provider or create_llm_provider(resolved_settings)
            app.state.llm_provider = active_provider
            app.state.indexing_service = IndexingService(
                database=app.state.database_manager,
                provider=active_provider,
                embedding_batch_size=resolved_settings.embedding_batch_size,
                embedding_dimensions=resolved_settings.embedding_dimensions,
            )
            app.state.retrieval_service = RetrievalService(
                database=app.state.database_manager,
                provider=active_provider,
                embedding_dimensions=resolved_settings.embedding_dimensions,
            )
            app.state.ask_service = AskService(
                retrieval=app.state.retrieval_service,
                provider=active_provider,
                default_top_k=resolved_settings.ask_default_top_k,
                max_top_k=resolved_settings.ask_max_top_k,
                minimum_evidence_count=resolved_settings.ask_min_evidence_count,
                minimum_retrieval_score=resolved_settings.ask_min_retrieval_score,
                maximum_evidence_chunks=resolved_settings.ask_max_evidence_chunks,
                evidence_max_chars_per_chunk=(resolved_settings.ask_evidence_max_chars_per_chunk),
                maximum_question_chars=resolved_settings.ask_max_question_chars,
                citation_excerpt_max_chars=resolved_settings.citation_excerpt_max_chars,
            )
            registry = AgentRegistry(
                timeout_seconds=resolved_settings.agent_timeout_seconds,
                maximum_retries=resolved_settings.agent_max_retries,
            )
            tools = build_tool_executor(
                registry=registry,
                retrieval=app.state.retrieval_service,
                minimum_evidence_count=resolved_settings.ask_min_evidence_count,
                minimum_retrieval_score=resolved_settings.ask_min_retrieval_score,
                maximum_evidence_items=resolved_settings.agent_max_evidence_items,
                evidence_max_chars_per_chunk=(resolved_settings.ask_evidence_max_chars_per_chunk),
            )
            app.state.agentic_ask_service = AgenticAskService(
                baseline=app.state.ask_service,
                coordinator=Coordinator(
                    registry=registry,
                    maximum_tasks=resolved_settings.agent_max_tasks,
                ),
                registry=registry,
                retrieval_specialist=RetrievalSpecialist(tools=tools),
                policy_analyst=PolicyAnalyst(provider=active_provider),
                support_specialist=StudentSupportSpecialist(provider=active_provider),
                verifier=WorkflowVerifier(),
                maximum_tasks=resolved_settings.agent_max_tasks,
                maximum_tool_calls=resolved_settings.agent_max_tool_calls,
                maximum_evidence_items=resolved_settings.agent_max_evidence_items,
                maximum_provider_calls=resolved_settings.agent_max_provider_calls,
            )
            logger.info(
                "LLM provider initialised",
                extra={
                    "llm_provider": active_provider.name,
                    "llm_model": active_provider.model,
                    "embedding_model": active_provider.embedding_model,
                },
            )
        except LLMConfigurationError as exc:
            app.state.llm_provider_error = exc.message
            logger.error(
                "LLM provider configuration failed",
                extra={
                    "llm_provider": resolved_settings.llm_provider.value,
                    "error_code": exc.code,
                    "details": exc.details,
                },
            )

        active_evaluation_provider: EvaluationProvider | None = None
        try:
            active_evaluation_provider = evaluation_provider or create_evaluation_provider(
                resolved_settings
            )
            app.state.evaluation_provider = active_evaluation_provider
            if app.state.ask_service is not None and app.state.agentic_ask_service is not None:
                app.state.evaluation_runner = EvaluationRunner(
                    dataset=EvaluationDataset(resolved_settings.evaluation_dataset_path),
                    baseline=app.state.ask_service,
                    agentic=app.state.agentic_ask_service,
                    provider=active_evaluation_provider,
                    observability=app.state.observability,
                    maximum_cases=resolved_settings.eval_max_cases_per_run,
                    maximum_judge_calls=resolved_settings.eval_max_judge_calls,
                    timeout_seconds=resolved_settings.eval_timeout_seconds,
                )
            logger.info(
                "Evaluation provider initialised",
                extra={
                    "evaluation_provider": active_evaluation_provider.name,
                    "evaluation_model": active_evaluation_provider.model,
                },
            )
        except EvaluationError as exc:
            app.state.evaluation_provider_error = exc.code
            logger.info(
                "Evaluation provider is unavailable",
                extra={"error_code": exc.code},
            )

        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False
            app.state.document_manager = None
            app.state.indexing_service = None
            app.state.retrieval_service = None
            app.state.ask_service = None
            app.state.agentic_ask_service = None
            app.state.memory_service = None
            app.state.audit_service = None
            app.state.rate_limit_service = None
            app.state.evaluation_runner = None
            try:
                try:
                    if active_evaluation_provider is not None:
                        await active_evaluation_provider.close()
                finally:
                    app.state.evaluation_provider = None
                    if active_provider is not None:
                        await active_provider.close()
            finally:
                try:
                    await app.state.observability.close()
                    app.state.observability = None
                finally:
                    if app.state.identity_service is not None:
                        await app.state.identity_service.close()
                    app.state.identity_service = None
                    await app.state.auth_service.close()
                    app.state.auth_service = None
                    await app.state.database_manager.close()
                    app.state.database_manager = None
            logger.info("Application stopped")

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "A grounded assistant that helps university students understand "
            "policies and identify practical next steps."
        ),
        docs_url="/docs" if resolved_settings.docs_enabled else None,
        redoc_url="/redoc" if resolved_settings.docs_enabled else None,
        openapi_url="/openapi.json" if resolved_settings.docs_enabled else None,
        lifespan=lifespan,
    )

    app.state.settings = resolved_settings
    app.state.ready = False
    app.state.started_at = datetime.now(UTC)
    app.state.llm_provider = None
    app.state.llm_provider_error = None
    app.state.observability = None
    app.state.evaluation_provider = None
    app.state.evaluation_provider_error = None
    app.state.evaluation_runner = None
    app.state.document_manager = None
    app.state.database_manager = None
    app.state.indexing_service = None
    app.state.retrieval_service = None
    app.state.ask_service = None
    app.state.agentic_ask_service = None
    app.state.auth_service = None
    app.state.identity_service = None
    app.state.memory_service = None
    app.state.audit_service = None
    app.state.rate_limit_service = None

    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    app.add_middleware(
        SecurityMiddleware,
        maximum_body_bytes=resolved_settings.request_body_max_bytes,
        production=resolved_settings.is_production,
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(service_router)
    app.include_router(v1_router, prefix=resolved_settings.api_v1_prefix)

    return app


app = create_app()
