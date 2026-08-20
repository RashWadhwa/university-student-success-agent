"""Tests for Stage 2 provider diagnostic endpoints."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import Environment, LLMProviderName, Settings
from backend.main import create_app


def test_llm_status_reports_mock_provider(client: TestClient) -> None:
    response = client.get("/api/v1/llm/status")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "mock",
        "model": "mock-generation-v1",
        "embedding_model": "mock-embedding-v1",
        "configured": True,
        "smoke_test_enabled": True,
        "configuration_error": None,
    }


def test_llm_smoke_test_returns_structured_result(client: TestClient) -> None:
    response = client.post("/api/v1/llm/smoke-test")

    assert response.status_code == 200
    body = response.json()
    assert body["output"] == {
        "message": "Provider is ready.",
        "provider_ready": True,
    }
    assert body["provider"] == "mock"
    assert body["usage"]["total_tokens"] == 0


def test_missing_openai_key_keeps_liveness_but_fails_readiness() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.OPENAI,
        openai_api_key=None,
        cors_origins=[],
    )
    app: FastAPI = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        status = client.get("/api/v1/llm/status")
        smoke = client.post("/api/v1/llm/smoke-test")

    assert ready.status_code == 503
    assert ready.json()["error"]["details"] == {
        "failed_checks": ["llm_provider"]
    }
    assert status.json()["configured"] is False
    assert smoke.status_code == 503
    assert smoke.json()["error"]["code"] == "LLM_CONFIGURATION_ERROR"


def test_smoke_test_is_disabled_in_production() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        llm_provider=LLMProviderName.MOCK,
        enable_llm_smoke_test=True,
        cors_origins=[],
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.post("/api/v1/llm/smoke-test")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LLM_SMOKE_TEST_DISABLED"
