"""Tests for ingestion orchestration, security, deduplication, and persistence."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.documents.errors import DuplicateDocumentError, InvalidDocumentError
from backend.documents.manager import DocumentManager
from tests.pdf_factory import make_pdf


@dataclass
class UploadStub:
    content: bytes
    filename: str | None = "handbook.pdf"
    content_type: str | None = "application/pdf"

    async def read(self, size: int = -1) -> bytes:
        return self.content if size < 0 else self.content[:size]


def manager(storage_path: Path, *, max_size: int = 1024 * 1024) -> DocumentManager:
    return DocumentManager(
        storage_path=storage_path,
        max_file_size_bytes=max_size,
        chunk_size=240,
        chunk_overlap=40,
    )


@pytest.mark.asyncio
async def test_ingestion_hashes_chunks_and_persists_metadata(tmp_path: Path) -> None:
    content = make_pdf(
        "ACADEMIC PROGRESS\nStudents must pass each required module. " * 12,
        title="Academic Handbook",
    )

    record = await manager(tmp_path).ingest(
        UploadStub(content=content, filename="Student Handbook (2026).PDF")
    )

    assert record.original_filename == "Student_Handbook_2026.pdf"
    assert record.stored_filename == f"{record.checksum_sha256}.pdf"
    assert record.page_count == 1
    assert record.chunk_count > 1
    assert record.pages[0].page_number == 1
    assert record.metadata["/Title"] == "Academic Handbook"
    assert (tmp_path / record.stored_filename).read_bytes() == content
    assert (tmp_path / f"{record.id}.json").is_file()


@pytest.mark.asyncio
async def test_duplicate_is_detected_after_repository_restart(tmp_path: Path) -> None:
    content = make_pdf("A policy document with sufficient extractable text.")
    first = await manager(tmp_path).ingest(UploadStub(content=content))

    with pytest.raises(DuplicateDocumentError) as exc_info:
        await manager(tmp_path).ingest(UploadStub(content=content, filename="copy.pdf"))

    assert exc_info.value.details == {
        "checksum": first.checksum_sha256,
        "document_id": first.id,
    }


@pytest.mark.parametrize("filename", ["../policy.pdf", "folder\\policy.pdf", "policy.txt", None])
def test_rejects_unsafe_or_non_pdf_filenames(filename: str | None) -> None:
    with pytest.raises(InvalidDocumentError):
        DocumentManager.secure_filename(filename)


@pytest.mark.asyncio
async def test_rejects_invalid_media_type_empty_and_oversized_uploads(tmp_path: Path) -> None:
    service = manager(tmp_path, max_size=1024)

    with pytest.raises(InvalidDocumentError) as wrong_type:
        await service.ingest(UploadStub(content=b"data", content_type="text/plain"))
    assert wrong_type.value.code == "DOCUMENT_TYPE_INVALID"

    with pytest.raises(InvalidDocumentError) as empty:
        await service.ingest(UploadStub(content=b""))
    assert empty.value.code == "DOCUMENT_EMPTY"

    with pytest.raises(InvalidDocumentError) as large:
        await service.ingest(UploadStub(content=b"x" * 1025))
    assert large.value.code == "DOCUMENT_TOO_LARGE"
    assert large.value.status_code == 413
