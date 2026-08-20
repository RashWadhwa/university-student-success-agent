"""Tests for request-validation error formatting."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_validation_errors_use_error_envelope(
    app: FastAPI,
    client: TestClient,
) -> None:
    @app.get("/_test/validate")
    async def validate(value: int) -> dict[str, int]:
        return {"value": value}

    response = client.get("/_test/validate", params={"value": "not-an-integer"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"][0]["location"] == ["query", "value"]
    assert body["request_id"] == response.headers["x-request-id"]
