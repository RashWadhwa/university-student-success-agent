"""Tests for Stage 1 service endpoints and middleware."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import Environment, LLMProviderName, Settings
from backend.database.manager import DatabaseReadiness
from backend.main import create_app


def test_root_describes_service(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Student Success Agent Test"
    assert body["environment"] == "testing"
    assert body["status"] == "running"
    assert body["documentation_url"].endswith("/docs")


def test_health_reports_liveness(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Student Success Agent Test"
    assert body["uptime_seconds"] >= 0


def test_health_does_not_depend_on_readiness_dependencies(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.ready = False
    app.state.llm_provider = None
    app.state.document_manager = None

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_reports_all_current_checks(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "application": "ok",
        "configuration": "ok",
        "llm_provider": "ok",
        "document_manager": "ok",
        "database": "ok",
        "pgvector": "ok",
    }


def test_ready_returns_structured_503_when_not_ready(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.ready = False

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
    assert response.json()["error"]["details"] == {"failed_checks": ["application"]}


def test_ready_reports_missing_document_manager(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.document_manager = None

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {"failed_checks": ["document_manager"]}


def test_ready_reports_database_and_pgvector_unavailable(tmp_path: Path) -> None:
    class UnavailableDatabase:
        async def check_readiness(self) -> DatabaseReadiness:
            return DatabaseReadiness(database=False, pgvector=False)

        async def close(self) -> None:
            return None

    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.MOCK,
        embedding_dimensions=8,
        document_storage_path=tmp_path / "documents",
        cors_origins=[],
    )
    unavailable_app = create_app(
        settings,
        database_manager=UnavailableDatabase(),  # type: ignore[arg-type]
    )

    with TestClient(unavailable_app) as unavailable_client:
        response = unavailable_client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["details"] == {"failed_checks": ["database", "pgvector"]}


def test_request_id_is_created_and_returned(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_valid_incoming_request_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "demo-request-123"})

    assert response.headers["x-request-id"] == "demo-request-123"


def test_invalid_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "not valid!"})

    assert response.headers["x-request-id"] != "not valid!"


def test_not_found_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "HTTP_ERROR"
    assert body["request_id"] == response.headers["x-request-id"]


def test_unhandled_error_uses_error_envelope(
    app: FastAPI,
    client: TestClient,
) -> None:
    @app.get("/_test/error")
    async def trigger_error() -> None:
        raise RuntimeError("test failure")

    response = client.get("/_test/error")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert body["request_id"] == response.headers["x-request-id"]
