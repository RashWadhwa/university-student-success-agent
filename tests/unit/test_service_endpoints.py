"""Tests for Stage 1 service endpoints and middleware."""

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.config import Environment, LLMProviderName, Settings
from backend.database.manager import DatabaseReadiness
from backend.main import create_app
from tests.conftest import ReadyDatabaseManager


def test_root_describes_service(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Student Success Agent Test"
    assert body["environment"] == "testing"
    assert body["status"] == "running"
    assert body["documentation_url"].endswith("/docs")


def test_local_authenticated_context_is_explicit_and_capability_bounded(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert "evaluation:run" in response.json()["capabilities"]


def test_student_is_denied_document_management(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        llm_provider=LLMProviderName.MOCK,
        eval_provider="mock",
        local_auth_role="student",
        embedding_dimensions=8,
        document_storage_path=tmp_path / "documents",
        cors_origins=[],
    )
    student_app = create_app(settings, database_manager=ReadyDatabaseManager())

    with TestClient(student_app) as test_client:
        response = test_client.post(
            "/api/v1/documents",
            files={"file": ("policy.pdf", b"%PDF-1.4", "application/pdf")},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


def test_health_reports_liveness(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "Student Success Agent Test"
    assert body["uptime_seconds"] >= 0
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


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


def test_oversized_request_is_rejected_safely(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ask",
        content=b"x" * (13 * 1024 * 1024),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"
    assert "traceback" not in response.text.casefold()


def test_rate_limit_response_is_safe_and_forwarded_header_cannot_bypass(
    app: FastAPI,
    client: TestClient,
) -> None:
    class DenyLimiter:
        async def allow(self, *, identity: str, bucket: str, limit: int) -> bool:
            del identity, bucket, limit
            return False

    app.state.rate_limit_service = DenyLimiter()
    response = client.post(
        "/api/v1/ask",
        headers={"X-Forwarded-For": "198.51.100.10"},
        json={"question": "How do extensions work?", "filters": {}},
    )

    assert response.status_code == 429
    assert response.json()["error"] == {
        "code": "RATE_LIMITED",
        "message": "Too many requests. Please try again later.",
    }
    assert "198.51.100.10" not in response.text


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


def test_unhandled_error_does_not_log_or_return_sensitive_exception_message(
    app: FastAPI,
    client: TestClient,
) -> None:
    sensitive_marker = "student-private-data-must-not-leak"

    @app.get("/_test/sensitive-error")
    async def trigger_sensitive_error() -> None:
        raise RuntimeError(sensitive_marker)

    with (
        patch("backend.core.exceptions.logger.error") as handler_log,
        patch("backend.core.middleware.logger.error") as middleware_log,
    ):
        response = client.get("/_test/sensitive-error")

    assert response.status_code == 500
    assert sensitive_marker not in response.text
    logged_calls = handler_log.call_args_list + middleware_log.call_args_list
    assert len(logged_calls) == 1
    logged = logged_calls[0]
    assert sensitive_marker not in repr(logged)
    assert logged.kwargs["extra"]["error_type"] == "RuntimeError"
