"""FastAPI application factory and ASGI entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import service_router, v1_router
from backend.core.config import Settings, get_settings
from backend.core.exceptions import register_exception_handlers
from backend.core.logging import configure_logging
from backend.core.middleware import RequestContextMiddleware
from backend.documents.manager import DocumentManager
from backend.llm.base import LLMProvider
from backend.llm.errors import LLMConfigurationError
from backend.llm.factory import create_llm_provider

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    llm_provider: LLMProvider | None = None,
    document_manager: DocumentManager | None = None,
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
                "document_storage_path": str(resolved_settings.document_storage_path),
            },
        )

        active_provider: LLMProvider | None = None
        try:
            active_provider = llm_provider or create_llm_provider(resolved_settings)
            app.state.llm_provider = active_provider
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

        app.state.ready = True
        try:
            yield
        finally:
            app.state.ready = False
            app.state.document_manager = None
            if active_provider is not None:
                await active_provider.close()
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
    app.state.document_manager = None

    if resolved_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(service_router)
    app.include_router(v1_router, prefix=resolved_settings.api_v1_prefix)

    return app


app = create_app()
