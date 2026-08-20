"""Tests for defensive PDF parsing and extraction."""

from io import BytesIO

import pytest
from pypdf import PdfWriter

from backend.documents.errors import InvalidDocumentError
from backend.documents.pdf import PDFProcessor
from tests.pdf_factory import make_encrypted_pdf, make_pdf


def error_code(content: bytes) -> str:
    with pytest.raises(InvalidDocumentError) as exc_info:
        PDFProcessor().extract(content)
    return exc_info.value.code


def test_extracts_page_text_and_metadata() -> None:
    result = PDFProcessor().extract(
        make_pdf("Academic regulations and progression requirements.", title="Regulations")
    )

    assert result.pages[0].page_number == 1
    assert "progression requirements" in result.pages[0].text
    assert result.pages[0].metadata["width_points"] == 612.0
    assert result.metadata["/Title"] == "Regulations"


def test_rejects_corrupt_and_non_pdf_content() -> None:
    assert error_code(b"%PDF-1.7\nnot a real pdf") == "PDF_CORRUPT"
    assert error_code(b"plain text") == "DOCUMENT_TYPE_INVALID"


def test_rejects_encrypted_pdf() -> None:
    assert error_code(make_encrypted_pdf()) == "PDF_ENCRYPTED"


def test_rejects_image_only_pdf() -> None:
    assert error_code(make_pdf("")) == "PDF_IMAGE_ONLY"


def test_rejects_pdf_without_pages() -> None:
    writer = PdfWriter()
    output = BytesIO()
    writer.write(output)

    assert error_code(output.getvalue()) == "PDF_EMPTY"
