"""Durable local document repository with checksum-based deduplication."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from threading import RLock

from backend.documents.errors import DuplicateDocumentError
from backend.documents.models import DocumentRecord

logger = logging.getLogger(__name__)


class FileSystemDocumentRepository:
    """Persist PDFs and typed JSON sidecars under one controlled directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._by_checksum: dict[str, DocumentRecord] = {}
        self._load_existing()

    def find_by_checksum(self, checksum: str) -> DocumentRecord | None:
        with self._lock:
            return self._by_checksum.get(checksum)

    def save(self, record: DocumentRecord, content: bytes) -> None:
        with self._lock:
            existing = self._by_checksum.get(record.checksum_sha256)
            if existing is not None:
                raise DuplicateDocumentError(
                    checksum=record.checksum_sha256,
                    document_id=existing.id,
                )

            pdf_path = self._safe_path(record.stored_filename)
            metadata_path = self._safe_path(f"{record.id}.json")
            self._atomic_write(pdf_path, content)
            try:
                self._atomic_write(
                    metadata_path,
                    record.model_dump_json(indent=2).encode("utf-8"),
                )
            except Exception:
                pdf_path.unlink(missing_ok=True)
                raise
            self._by_checksum[record.checksum_sha256] = record

    def _load_existing(self) -> None:
        for path in self.root.glob("*.json"):
            try:
                record = DocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
                self._by_checksum[record.checksum_sha256] = record
            except Exception as exc:
                logger.warning(
                    "Ignoring invalid document metadata sidecar",
                    extra={"metadata_file": path.name, "error_type": type(exc).__name__},
                )

    def _safe_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("repository filenames must not contain path components")
        candidate = (self.root / filename).resolve()
        if candidate.parent != self.root:
            raise ValueError("repository path escaped its configured root")
        return candidate

    @staticmethod
    def _atomic_write(destination: Path, content: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(destination)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
