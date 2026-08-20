"""Tests for the controlled official-policy corpus loader."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from backend.corpus.loader import (
    CorpusLoadError,
    CuratedCorpusLoader,
    OfficialPDFDownloader,
    RetrievedPDF,
    load_manifest,
)
from backend.corpus.models import CorpusDocument
from backend.evaluation.dataset import EvaluationDataset
from backend.rag.types import IndexingResult


def corpus_document(url: str) -> CorpusDocument:
    return CorpusDocument(
        id="policy-one",
        filename="policy-one.pdf",
        title="Policy One",
        source_url=url,
        document_type="assessment_policy",
        version="1.0",
        policy_domains=["extensions"],
    )


def test_repository_manifest_is_small_official_and_institution_neutral() -> None:
    path = Path("data/institutions/primary-corpus.json")
    manifest = load_manifest(path)
    source = json.loads(path.read_text(encoding="utf-8"))

    assert 1 <= len(manifest.documents) <= 10
    assert "institution" not in source
    assert manifest.corpus_tier.value == "primary"
    assert manifest.authority_scope.value == "institution_policy"
    assert all(document.source_url.startswith("https://") for document in manifest.documents)
    assert all("harper-adams.ac.uk" in document.source_url for document in manifest.documents)
    domains = {domain for document in manifest.documents for domain in document.policy_domains}
    assert {
        "mitigating circumstances",
        "extensions",
        "late submission",
        "missed assessment",
        "reassessment",
        "academic appeals",
    } <= domains


def test_representative_validation_questions_use_existing_typed_contract() -> None:
    cases = EvaluationDataset(Path("data/evaluation/primary-institution-validation.jsonl")).load()

    assert len(cases) == 7
    assert {case.category for case in cases} >= {
        "extensions",
        "late submission",
        "missed assessment",
        "reassessment",
        "academic appeals",
        "student support",
    }


@pytest.mark.asyncio
async def test_downloader_accepts_only_bounded_pdf_from_allowed_https_host() -> None:
    pdf = b"%PDF-1.4 safe public policy"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={
                    "content-type": "application/pdf",
                    "content-length": str(len(pdf)),
                    "etag": '"public-version"',
                },
                content=pdf,
            )
        )
    )
    downloader = OfficialPDFDownloader(
        allowed_hosts=["policies.example.edu"],
        max_size_bytes=1024,
        timeout_seconds=2,
        client=client,
    )

    retrieved = await downloader.fetch(
        corpus_document("https://policies.example.edu/assessment/policy.pdf")
    )

    assert retrieved.content == pdf
    assert retrieved.content_type == "application/pdf"
    assert retrieved.etag == '"public-version"'
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "status", "content_type", "content_length", "expected_code"),
    [
        (
            "https://untrusted.example/policy.pdf",
            200,
            "application/pdf",
            "10",
            "CORPUS_SOURCE_NOT_ALLOWED",
        ),
        (
            "https://policies.example.edu/policy.pdf",
            302,
            "application/pdf",
            "10",
            "CORPUS_SOURCE_UNAVAILABLE",
        ),
        (
            "https://policies.example.edu/policy.pdf",
            200,
            "text/html",
            "10",
            "CORPUS_SOURCE_TYPE_INVALID",
        ),
        (
            "https://policies.example.edu/policy.pdf",
            200,
            "application/pdf",
            "2048",
            "CORPUS_SOURCE_TOO_LARGE",
        ),
    ],
)
async def test_downloader_fails_closed_for_unsafe_sources(
    url: str,
    status: int,
    content_type: str,
    content_length: str,
    expected_code: str,
) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                headers={"content-type": content_type, "content-length": content_length},
                content=b"%PDF-data",
            )
        )
    )
    downloader = OfficialPDFDownloader(
        allowed_hosts=["policies.example.edu"],
        max_size_bytes=1024,
        timeout_seconds=2,
        client=client,
    )

    with pytest.raises(CorpusLoadError) as captured:
        await downloader.fetch(corpus_document(url))

    assert captured.value.code == expected_code
    await client.aclose()


@pytest.mark.asyncio
async def test_loader_injects_configured_institution_and_retrieval_metadata() -> None:
    manifest = load_manifest(Path("data/institutions/primary-corpus.json"))
    selected = manifest.model_copy(update={"documents": manifest.documents[:1]})
    record = SimpleNamespace(id="record-id", chunks=[SimpleNamespace(text="policy")])

    class Source:
        async def fetch(self, document: CorpusDocument) -> RetrievedPDF:
            return RetrievedPDF(
                content=b"%PDF-public",
                content_type="application/pdf",
                retrieved_at=datetime(2026, 8, 20, tzinfo=UTC),
                last_modified="Wed, 20 Aug 2026 10:00:00 GMT",
            )

    class Manager:
        async def ingest(self, upload: Any) -> object:
            assert upload.filename == selected.documents[0].filename
            return record

        def get_document(self, document_id: str) -> None:
            del document_id
            return None

    class Indexing:
        metadata: object | None = None

        async def index_document(self, received: object, metadata: object) -> IndexingResult:
            assert received is record
            self.metadata = metadata
            return IndexingResult(
                document_id="indexed-id",
                status="indexed",
                chunk_count=3,
                embedding_model="mock-embedding-v1",
                indexed_at=datetime(2026, 8, 20, tzinfo=UTC),
            )

    indexing = Indexing()
    summary = await CuratedCorpusLoader(
        institution="Configurable University",
        manager=Manager(),  # type: ignore[arg-type]
        indexing=indexing,  # type: ignore[arg-type]
        source=Source(),
    ).load(selected)

    metadata = indexing.metadata
    assert metadata is not None
    assert metadata.institution == "Configurable University"  # type: ignore[attr-defined]
    assert metadata.corpus_tier.value == "primary"  # type: ignore[attr-defined]
    assert metadata.authority_scope.value == "institution_policy"  # type: ignore[attr-defined]
    assert metadata.source == selected.documents[0].source_url  # type: ignore[attr-defined]
    assert metadata.retrieval_metadata["method"] == "curated_https_download"  # type: ignore[attr-defined]
    assert metadata.retrieval_metadata["last_modified"]  # type: ignore[attr-defined]
    assert summary.indexed_count == 1
    assert summary.documents[0].source_url == selected.documents[0].source_url
