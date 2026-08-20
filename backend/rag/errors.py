"""Indexing and retrieval errors safe for API responses."""

from typing import Any

from backend.core.exceptions import ApplicationError


class DocumentNotFoundError(ApplicationError):
    def __init__(self, document_id: str) -> None:
        super().__init__(
            code="DOCUMENT_NOT_FOUND",
            message="The ingested document was not found.",
            status_code=404,
            details={"document_id": document_id},
        )


class IndexingError(ApplicationError):
    def __init__(self, *, code: str, message: str, details: Any | None = None) -> None:
        super().__init__(code=code, message=message, status_code=500, details=details)


class RetrievalUnavailableError(ApplicationError):
    def __init__(self, details: Any | None = None) -> None:
        super().__init__(
            code="RETRIEVAL_UNAVAILABLE",
            message="Retrieval is temporarily unavailable.",
            status_code=503,
            details=details,
        )
