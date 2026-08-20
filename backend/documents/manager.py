"""Document ingestion orchestration service."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from backend.documents.chunking import StructureAwareChunker
from backend.documents.errors import DuplicateDocumentError, InvalidDocumentError
from backend.documents.models import DocumentRecord
from backend.documents.pdf import PDFProcessor
from backend.documents.repository import FileSystemDocumentRepository

logger = logging.getLogger(__name__)
_SAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}


class AsyncUpload(Protocol):
    """Minimal upload contract required by the ingestion service."""

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes: ...


class DocumentManager:
    """Validate, deduplicate, extract, chunk, and persist uploaded documents."""

    def __init__(
        self,
        *,
        storage_path: Path,
        max_file_size_bytes: int,
        chunk_size: int,
        chunk_overlap: int,
        repository: FileSystemDocumentRepository | None = None,
        pdf_processor: PDFProcessor | None = None,
    ) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        self.repository = repository or FileSystemDocumentRepository(storage_path)
        self.pdf_processor = pdf_processor or PDFProcessor()
        self.chunker = StructureAwareChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def ingest(self, upload: AsyncUpload) -> DocumentRecord:
        safe_filename = self.secure_filename(upload.filename)
        self._validate_media_type(upload.content_type)
        content = await upload.read(self.max_file_size_bytes + 1)
        if not content:
            raise InvalidDocumentError(
                code="DOCUMENT_EMPTY",
                message="The uploaded file is empty.",
            )
        if len(content) > self.max_file_size_bytes:
            raise InvalidDocumentError(
                code="DOCUMENT_TOO_LARGE",
                message="The uploaded file exceeds the configured size limit.",
                status_code=413,
                details={"max_size_bytes": self.max_file_size_bytes},
            )

        return await asyncio.to_thread(self._ingest_content, safe_filename, content)

    def _ingest_content(self, safe_filename: str, content: bytes) -> DocumentRecord:
        """Perform CPU-bound parsing and durable writes outside the event loop."""

        checksum = hashlib.sha256(content).hexdigest()
        existing = self.repository.find_by_checksum(checksum)
        if existing is not None:
            raise DuplicateDocumentError(checksum=checksum, document_id=existing.id)

        extraction = self.pdf_processor.extract(content)
        chunks = self.chunker.chunk(extraction.pages)
        if not chunks:
            raise InvalidDocumentError(
                code="PDF_IMAGE_ONLY",
                message="The PDF contains no extractable text; image-only PDFs are not supported.",
            )

        document_id = str(uuid4())
        stored_filename = f"{checksum}.pdf"
        record = DocumentRecord(
            id=document_id,
            original_filename=safe_filename,
            stored_filename=stored_filename,
            media_type="application/pdf",
            size_bytes=len(content),
            checksum_sha256=checksum,
            page_count=len(extraction.pages),
            chunk_count=len(chunks),
            created_at=datetime.now(UTC),
            metadata=extraction.metadata,
            pages=extraction.pages,
            chunks=chunks,
        )
        self.repository.save(record, content)
        logger.info(
            "Document ingested",
            extra={
                "document_id": record.id,
                "checksum_sha256": record.checksum_sha256,
                "page_count": record.page_count,
                "chunk_count": record.chunk_count,
                "size_bytes": record.size_bytes,
            },
        )
        return record

    @staticmethod
    def secure_filename(filename: str | None) -> str:
        if not filename or not filename.strip():
            raise InvalidDocumentError(
                code="DOCUMENT_FILENAME_INVALID",
                message="A PDF filename is required.",
            )
        if "\x00" in filename or "/" in filename or "\\" in filename:
            raise InvalidDocumentError(
                code="DOCUMENT_FILENAME_INVALID",
                message="The filename contains invalid path components.",
            )

        normalised = unicodedata.normalize("NFKC", filename).strip()
        if Path(normalised).suffix.lower() != ".pdf":
            raise InvalidDocumentError(
                code="DOCUMENT_TYPE_INVALID",
                message="Only PDF uploads are supported.",
            )
        stem = _SAFE_FILENAME_CHARS.sub("_", Path(normalised).stem).strip("._-")
        if not stem:
            stem = "document"
        return f"{stem[:110]}.pdf"

    @staticmethod
    def _validate_media_type(content_type: str | None) -> None:
        resolved = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if resolved not in _PDF_MEDIA_TYPES:
            raise InvalidDocumentError(
                code="DOCUMENT_TYPE_INVALID",
                message="Only PDF uploads are supported.",
                details={"content_type": resolved or None},
            )
