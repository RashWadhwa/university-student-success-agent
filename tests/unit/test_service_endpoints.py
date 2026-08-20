"""Tests for Stage 1 service endpoints and middleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


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


def test_ready_reports_all_current_checks(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "application": "ok",
        "configuration": "ok",
        "llm_provider": "ok",
    }


def test_ready_returns_structured_503_when_not_ready(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.ready = False

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
    assert response.json()["error"]["details"] == {
        "failed_checks": ["application"]
    }


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
