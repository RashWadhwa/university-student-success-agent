"""Strict contracts for a small, reviewed public-policy corpus."""

from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from backend.rag.types import AuthorityScope, CorpusTier
from backend.schemas.common import StrictModel


def validate_public_https_url(value: str) -> str:
    """Reject credentials, fragments, and non-HTTPS locations in source metadata."""

    cleaned = value.strip()
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.port not in (None, 443)
    ):
        raise ValueError("source URLs must be credential-free HTTPS URLs without fragments")
    return cleaned


class CorpusDocument(StrictModel):
    """One explicitly selected official PDF and its policy metadata."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    filename: str = Field(min_length=5, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    source_url: str = Field(min_length=8, max_length=2048)
    document_type: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,99}$")
    effective_date: date | None = None
    review_date: date | None = None
    approval_date_text: str | None = Field(default=None, min_length=1, max_length=100)
    effective_date_text: str | None = Field(default=None, min_length=1, max_length=100)
    review_date_text: str | None = Field(default=None, min_length=1, max_length=100)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    policy_domains: list[str] = Field(min_length=1, max_length=12)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if "/" in value or "\\" in value or not value.casefold().endswith(".pdf"):
            raise ValueError("corpus filenames must be plain PDF filenames")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return validate_public_https_url(value)

    @field_validator("policy_domains")
    @classmethod
    def validate_policy_domains(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip().casefold() for value in values]
        if any(not value or len(value) > 100 for value in cleaned):
            raise ValueError("policy domains must be non-empty and at most 100 characters")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("policy domains must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_dates(self) -> CorpusDocument:
        if (
            self.effective_date is not None
            and self.review_date is not None
            and self.review_date < self.effective_date
        ):
            raise ValueError("review date cannot precede effective date")
        return self


class CorpusManifest(StrictModel):
    """Reviewed source list; intentionally not a crawler configuration."""

    schema_version: Literal[1]
    verified_at: date
    source_catalog_url: str = Field(min_length=8, max_length=2048)
    corpus_tier: Literal[CorpusTier.PRIMARY]
    authority_scope: Literal[AuthorityScope.INSTITUTION_POLICY]
    documents: list[CorpusDocument] = Field(min_length=1, max_length=25)

    @field_validator("source_catalog_url")
    @classmethod
    def validate_source_catalog_url(cls, value: str) -> str:
        return validate_public_https_url(value)

    @model_validator(mode="after")
    def validate_unique_documents(self) -> CorpusManifest:
        ids = [document.id for document in self.documents]
        urls = [document.source_url for document in self.documents]
        if len(ids) != len(set(ids)) or len(urls) != len(set(urls)):
            raise ValueError("corpus document IDs and source URLs must be unique")
        return self


class CorpusLoadItem(StrictModel):
    corpus_document_id: str
    document_id: str
    status: Literal["indexed", "already_indexed"]
    chunk_count: int = Field(ge=0)
    source_url: str


class CorpusLoadSummary(StrictModel):
    institution: str
    document_count: int = Field(ge=0)
    indexed_count: int = Field(ge=0)
    already_indexed_count: int = Field(ge=0)
    documents: list[CorpusLoadItem]
