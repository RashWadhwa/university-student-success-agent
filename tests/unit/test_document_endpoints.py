"""API tests for Stage 3 PDF document ingestion."""

from fastapi.testclient import TestClient

from tests.pdf_factory import make_pdf


def test_upload_pdf_returns_typed_document_metadata(client: TestClient) -> None:
    content = make_pdf(
        "ASSESSMENT POLICY\nStudents should review feedback before submitting an appeal.",
        title="Assessment Policy",
    )

    response = client.post(
        "/api/v1/documents",
        files={"file": ("assessment policy.pdf", content, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ingested"
    assert body["document"]["original_filename"] == "assessment policy.pdf"
    assert body["document"]["safe_filename"] == "assessment_policy.pdf"
    assert body["document"]["page_count"] == 1
    assert body["document"]["metadata"]["/Title"] == "Assessment Policy"
    assert body["document"]["pages"][0]["page_number"] == 1
    assert body["document"]["chunks"][0]["page_start"] == 1
    assert len(body["document"]["checksum_sha256"]) == 64


def test_duplicate_upload_returns_existing_document_id(client: TestClient) -> None:
    content = make_pdf("The same regulations are uploaded twice.")
    files = {"file": ("regulations.pdf", content, "application/pdf")}
    first = client.post("/api/v1/documents", files=files)
    duplicate = client.post("/api/v1/documents", files=files)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DOCUMENT_DUPLICATE"
    assert duplicate.json()["error"]["details"]["document_id"] == first.json()["document"]["id"]


def test_upload_rejects_path_traversal_and_wrong_content_type(client: TestClient) -> None:
    content = make_pdf("Policy text")
    traversal = client.post(
        "/api/v1/documents",
        files={"file": ("../policy.pdf", content, "application/pdf")},
    )
    wrong_type = client.post(
        "/api/v1/documents",
        files={"file": ("policy.pdf", content, "text/plain")},
    )

    assert traversal.status_code == 400
    assert traversal.json()["error"]["code"] == "DOCUMENT_FILENAME_INVALID"
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"]["code"] == "DOCUMENT_TYPE_INVALID"


def test_upload_rejects_corrupt_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/v1/documents",
        files={"file": ("broken.pdf", b"%PDF-1.7 broken", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PDF_CORRUPT"
