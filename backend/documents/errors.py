"""Document-ingestion errors safe for API responses."""

from typing import Any

from backend.core.exceptions import ApplicationError


class DocumentError(ApplicationError):
    """Base exception for expected document-ingestion failures."""


class InvalidDocumentError(DocumentError):
    """Raised when an upload cannot be accepted or parsed."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: Any | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            details=details,
        )


class DuplicateDocumentError(DocumentError):
    """Raised when the same document bytes were previously ingested."""

    def __init__(self, *, checksum: str, document_id: str) -> None:
        super().__init__(
            code="DOCUMENT_DUPLICATE",
            message="This document has already been ingested.",
            status_code=409,
            details={"checksum": checksum, "document_id": document_id},
        )
