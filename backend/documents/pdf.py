"""Defensive PDF validation and text extraction."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from backend.documents.errors import InvalidDocumentError
from backend.documents.models import PageRecord


class PDFExtractionResult:
    """Extracted PDF content before chunking and persistence."""

    def __init__(self, *, pages: list[PageRecord], metadata: dict[str, str]) -> None:
        self.pages = pages
        self.metadata = metadata


class PDFProcessor:
    """Validate a PDF container and extract page-aware text."""

    def extract(self, content: bytes) -> PDFExtractionResult:
        if not content:
            raise InvalidDocumentError(
                code="DOCUMENT_EMPTY",
                message="The uploaded file is empty.",
            )
        if not content[:1024].lstrip().startswith(b"%PDF-"):
            raise InvalidDocumentError(
                code="DOCUMENT_TYPE_INVALID",
                message="The uploaded file is not a valid PDF.",
            )

        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError
        except ImportError as exc:  # pragma: no cover - deployment packaging guard
            raise RuntimeError("pypdf is required for PDF ingestion") from exc

        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted:
                raise InvalidDocumentError(
                    code="PDF_ENCRYPTED",
                    message="Encrypted PDFs are not supported.",
                )
            if not reader.pages:
                raise InvalidDocumentError(
                    code="PDF_EMPTY",
                    message="The PDF does not contain any pages.",
                )

            pages: list[PageRecord] = []
            for page_number, page in enumerate(reader.pages, start=1):
                extracted = page.extract_text() or ""
                text = self._normalise_text(extracted)
                pages.append(
                    PageRecord(
                        page_number=page_number,
                        text=text,
                        char_count=len(text),
                        metadata=self._page_metadata(page),
                    )
                )
        except InvalidDocumentError:
            raise
        except (PdfReadError, EOFError, ValueError, TypeError, OSError) as exc:
            raise InvalidDocumentError(
                code="PDF_CORRUPT",
                message="The PDF is corrupt or cannot be read.",
            ) from exc
        except Exception as exc:
            raise InvalidDocumentError(
                code="PDF_CORRUPT",
                message="The PDF is corrupt or cannot be read.",
            ) from exc

        if not any(page.text.strip() for page in pages):
            raise InvalidDocumentError(
                code="PDF_IMAGE_ONLY",
                message="The PDF contains no extractable text; image-only PDFs are not supported.",
            )

        metadata = self._document_metadata(getattr(reader, "metadata", None))
        return PDFExtractionResult(pages=pages, metadata=metadata)

    @staticmethod
    def _normalise_text(text: str) -> str:
        lines = [line.rstrip() for line in text.replace("\x00", "").splitlines()]
        return "\n".join(lines).strip()

    @staticmethod
    def _document_metadata(metadata: Any | None) -> dict[str, str]:
        if not metadata:
            return {}
        result: dict[str, str] = {}
        for key, value in metadata.items():
            if value is not None:
                result[str(key)] = str(value)
        return result

    @staticmethod
    def _page_metadata(page: Any) -> dict[str, Any]:
        box = getattr(page, "mediabox", None)
        metadata: dict[str, Any] = {
            "rotation": int(getattr(page, "rotation", 0) or 0),
        }
        if box is not None:
            try:
                metadata["width_points"] = float(box.width)
                metadata["height_points"] = float(box.height)
            except (TypeError, ValueError):
                pass
        return metadata
