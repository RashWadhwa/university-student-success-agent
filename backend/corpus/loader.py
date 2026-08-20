"""Securely load a reviewed official corpus through existing ingestion and indexing."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from backend.core.exceptions import ApplicationError
from backend.corpus.models import (
    CorpusDocument,
    CorpusLoadItem,
    CorpusLoadSummary,
    CorpusManifest,
)
from backend.documents.errors import DuplicateDocumentError
from backend.documents.manager import DocumentManager
from backend.rag.indexing import IndexingService
from backend.rag.types import DocumentIndexMetadata

logger = logging.getLogger(__name__)
_PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}


class CorpusLoadError(ApplicationError):
    """Safe failure for manifest validation or official-source retrieval."""

    def __init__(self, code: str = "CORPUS_LOAD_FAILED") -> None:
        super().__init__(
            code=code,
            message="The curated policy corpus could not be loaded safely.",
            status_code=502,
        )


@dataclass(frozen=True, slots=True)
class RetrievedPDF:
    content: bytes
    content_type: str
    retrieved_at: datetime
    etag: str | None = None
    last_modified: str | None = None


class CorpusPDFSource(Protocol):
    async def fetch(self, document: CorpusDocument) -> RetrievedPDF: ...


class MemoryPDFUpload:
    """Minimal in-memory adapter for the existing DocumentManager contract."""

    def __init__(self, filename: str, content: bytes, content_type: str) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        return self._content if size < 0 else self._content[:size]


class OfficialPDFDownloader:
    """Bounded HTTPS downloader restricted to configured official hostnames."""

    def __init__(
        self,
        *,
        allowed_hosts: list[str],
        max_size_bytes: int,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)
        self.max_size_bytes = max_size_bytes
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
            follow_redirects=False,
            headers={"Accept": "application/pdf", "User-Agent": "student-success-corpus/1"},
        )

    async def fetch(self, document: CorpusDocument) -> RetrievedPDF:
        parsed = urlsplit(document.source_url)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in self.allowed_hosts:
            raise CorpusLoadError("CORPUS_SOURCE_NOT_ALLOWED")
        try:
            async with self.client.stream("GET", document.source_url) as response:
                if response.status_code != 200:
                    raise CorpusLoadError("CORPUS_SOURCE_UNAVAILABLE")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
                if content_type.casefold() not in _PDF_MEDIA_TYPES:
                    raise CorpusLoadError("CORPUS_SOURCE_TYPE_INVALID")
                declared_size = response.headers.get("content-length")
                if declared_size is not None:
                    try:
                        if int(declared_size) > self.max_size_bytes:
                            raise CorpusLoadError("CORPUS_SOURCE_TOO_LARGE")
                    except ValueError as exc:
                        raise CorpusLoadError("CORPUS_SOURCE_INVALID") from exc
                content = bytearray()
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > self.max_size_bytes:
                        raise CorpusLoadError("CORPUS_SOURCE_TOO_LARGE")
        except CorpusLoadError:
            raise
        except (httpx.HTTPError, TimeoutError) as exc:
            raise CorpusLoadError("CORPUS_SOURCE_UNAVAILABLE") from exc
        return RetrievedPDF(
            content=bytes(content),
            content_type=content_type,
            retrieved_at=datetime.now(UTC),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


class CuratedCorpusLoader:
    """Orchestrate public download, PDF ingestion, deduplication, and indexing."""

    def __init__(
        self,
        *,
        institution: str,
        manager: DocumentManager,
        indexing: IndexingService,
        source: CorpusPDFSource,
    ) -> None:
        self.institution = institution
        self.manager = manager
        self.indexing = indexing
        self.source = source

    async def load(self, manifest: CorpusManifest) -> CorpusLoadSummary:
        items: list[CorpusLoadItem] = []
        for document in manifest.documents:
            retrieved = await self.source.fetch(document)
            upload = MemoryPDFUpload(
                document.filename,
                retrieved.content,
                retrieved.content_type,
            )
            try:
                record = await self.manager.ingest(upload)
            except DuplicateDocumentError as exc:
                existing_id = str((exc.details or {}).get("document_id", ""))
                record = self.manager.get_document(existing_id)
                if record is None:
                    raise CorpusLoadError() from exc
            result = await self.indexing.index_document(
                record,
                DocumentIndexMetadata(
                    title=document.title,
                    document_type=document.document_type,
                    institution=self.institution,
                    effective_date=document.effective_date,
                    review_date=document.review_date,
                    version=document.version,
                    source=document.source_url,
                    corpus_tier=manifest.corpus_tier,
                    authority_scope=manifest.authority_scope,
                    retrieval_metadata={
                        "method": "curated_https_download",
                        "retrieved_at": retrieved.retrieved_at.isoformat(),
                        "content_type": retrieved.content_type,
                        "etag": retrieved.etag,
                        "last_modified": retrieved.last_modified,
                        "source_catalog_url": manifest.source_catalog_url,
                        "manifest_verified_at": manifest.verified_at.isoformat(),
                        "corpus_document_id": document.id,
                        "policy_domains": document.policy_domains,
                        "approval_date_text": document.approval_date_text,
                        "effective_date_text": document.effective_date_text,
                        "review_date_text": document.review_date_text,
                    },
                ),
            )
            items.append(
                CorpusLoadItem(
                    corpus_document_id=document.id,
                    document_id=result.document_id,
                    status=result.status,
                    chunk_count=result.chunk_count,
                    source_url=document.source_url,
                )
            )
            logger.info(
                "curated_corpus_document_processed",
                extra={"corpus_document_id": document.id, "status": result.status},
            )
        return CorpusLoadSummary(
            institution=self.institution,
            document_count=len(items),
            indexed_count=sum(item.status == "indexed" for item in items),
            already_indexed_count=sum(item.status == "already_indexed" for item in items),
            documents=items,
        )


def load_manifest(path: Path) -> CorpusManifest:
    """Read a local reviewed manifest without accepting remote manifest locations."""

    try:
        return CorpusManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise CorpusLoadError("CORPUS_MANIFEST_INVALID") from exc
