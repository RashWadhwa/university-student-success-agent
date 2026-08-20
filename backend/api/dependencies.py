"""FastAPI dependencies shared across API routes."""

from fastapi import Request

from backend.ask.service import AskService
from backend.core.exceptions import ServiceNotReadyError
from backend.documents.manager import DocumentManager
from backend.llm.base import LLMProvider
from backend.llm.errors import LLMConfigurationError
from backend.rag.indexing import IndexingService
from backend.rag.retrieval import RetrievalService


def get_llm_provider(request: Request) -> LLMProvider:
    """Return the initialised provider or a safe configuration error."""

    provider: LLMProvider | None = getattr(request.app.state, "llm_provider", None)
    if provider is None:
        error = getattr(request.app.state, "llm_provider_error", None)
        details = {"reason": error} if error else None
        raise LLMConfigurationError(details=details)
    return provider


def get_document_manager(request: Request) -> DocumentManager:
    """Return the application-scoped document ingestion service."""

    manager: DocumentManager | None = getattr(request.app.state, "document_manager", None)
    if manager is None:
        raise ServiceNotReadyError(details={"failed_checks": ["document_manager"]})
    return manager


def get_indexing_service(request: Request) -> IndexingService:
    service: IndexingService | None = getattr(request.app.state, "indexing_service", None)
    if service is None:
        raise ServiceNotReadyError(details={"failed_checks": ["indexing_service"]})
    return service


def get_retrieval_service(request: Request) -> RetrievalService:
    service: RetrievalService | None = getattr(request.app.state, "retrieval_service", None)
    if service is None:
        raise ServiceNotReadyError(details={"failed_checks": ["retrieval_service"]})
    return service


def get_ask_service(request: Request) -> AskService:
    service: AskService | None = getattr(request.app.state, "ask_service", None)
    if service is None:
        raise ServiceNotReadyError(details={"failed_checks": ["ask_service"]})
    return service
