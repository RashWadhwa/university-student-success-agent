"""Public institution configuration and API-default tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core.config import Settings
from backend.schemas.indexing import DocumentIndexRequest
from backend.schemas.retrieval import RetrievalFilters


def test_primary_institution_is_typed_config_with_override() -> None:
    settings = Settings(
        _env_file=None,
        primary_institution_name="  Configurable   University  ",
        primary_institution_source_hosts=["POLICIES.EXAMPLE.EDU."],
    )

    assert settings.primary_institution_name == "Configurable University"
    assert settings.primary_institution_source_hosts == ["policies.example.edu"]


def test_explicit_institution_filter_overrides_configured_default() -> None:
    retrieval = RetrievalFilters(institution="  Another   University ").to_domain(
        default_institution="Configured University"
    )
    indexing = DocumentIndexRequest(institution=" Another University ").to_domain(
        default_institution="Configured University"
    )

    assert retrieval.institution == "Another University"
    assert indexing.institution == "Another University"


def test_retrieval_defaults_to_primary_institution_policy_only() -> None:
    filters = RetrievalFilters().to_domain(default_institution="Configured University")

    assert filters.institution == "Configured University"
    assert filters.corpus_tier.value == "primary"  # type: ignore[union-attr]
    assert filters.authority_scope.value == "institution_policy"  # type: ignore[union-attr]


def test_secondary_guidance_requires_explicit_publisher_and_classification() -> None:
    with pytest.raises(ValidationError):
        DocumentIndexRequest(corpus_tier="synthetic")
    with pytest.raises(ValidationError):
        DocumentIndexRequest(
            corpus_tier="secondary",
            authority_scope="sector_guidance",
        )
    with pytest.raises(ValidationError):
        RetrievalFilters(
            institution="Discover Uni",
            corpus_tier="secondary",
            authority_scope="institution_policy",
        )

    metadata = DocumentIndexRequest(
        institution="Discover Uni",
        corpus_tier="secondary",
        authority_scope="sector_guidance",
        source="https://discoveruni.gov.uk/example",
    ).to_domain(default_institution="Configured University")

    assert metadata.institution == "Discover Uni"
    assert metadata.corpus_tier.value == "secondary"
    assert metadata.authority_scope.value == "sector_guidance"


def test_public_config_exposes_only_safe_institution_name(
    app: FastAPI,
    client: TestClient,
    test_settings: Settings,
) -> None:
    response = client.get("/api/v1/config/public")

    assert response.status_code == 200
    assert response.json() == {"primary_institution_name": test_settings.primary_institution_name}
    serialized = response.text.casefold()
    assert "api_key" not in serialized
    assert "database" not in serialized
    assert "source_hosts" not in serialized
