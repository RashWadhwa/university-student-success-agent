"""HTTP-only Streamlit API client tests with no live backend calls."""

import json
from pathlib import Path
from urllib.parse import urlunsplit

import httpx
import pytest

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient
from frontend.config import FrontendConfig


def client_for(handler: httpx.MockTransport) -> StudentSuccessAPIClient:
    http = httpx.Client(transport=handler, base_url="http://backend.test")
    return StudentSuccessAPIClient(
        FrontendConfig(api_base_url="http://backend.test", request_timeout_seconds=5),
        client=http,
    )


def test_health_success_and_retry_safe_read() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json={"status": "ok"})

    client = client_for(httpx.MockTransport(handle))

    assert client.health() == {"status": "ok"}
    assert calls == 2


def test_public_config_reads_safe_institution_display_value() -> None:
    client = client_for(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"primary_institution_name": "Configurable University"},
            )
        )
    )

    assert client.public_config() == {"primary_institution_name": "Configurable University"}


def test_access_token_is_sent_as_bearer_without_privileged_frontend_credentials() -> None:
    captured: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(200, json={"role": "student"})

    http = httpx.Client(transport=httpx.MockTransport(handle), base_url="http://backend.test")
    client = StudentSuccessAPIClient(
        FrontendConfig(api_base_url="http://backend.test", request_timeout_seconds=5),
        client=http,
        access_token="fixture-access-value",
    )

    assert client.current_user()["role"] == "student"
    assert captured["authorization"] == "Bearer fixture-access-value"


def test_health_failure_is_translated_without_backend_details() -> None:
    marker = "asyncpg password private-key"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            503,
            headers={"x-request-id": "request-safe"},
            json={"error": {"message": marker}},
        )
    )
    client = client_for(transport)

    with pytest.raises(FrontendAPIError) as captured:
        client.health()

    assert marker not in captured.value.safe_message
    assert captured.value.request_id == "request-safe"


@pytest.mark.parametrize(
    ("agentic", "expected_path"),
    [(False, "/api/v1/ask"), (True, "/api/v1/ask/agentic")],
)
def test_baseline_and_agentic_ask(agentic: bool, expected_path: str) -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"answer": "Safe grounded guidance."})

    client = client_for(httpx.MockTransport(handle))

    result = client.ask("How do extensions work?", agentic=agentic)

    assert result["answer"] == "Safe grounded guidance."
    assert captured["path"] == expected_path
    assert captured["payload"] == {
        "question": "How do extensions work?",
        "top_k": 5,
        "filters": {},
    }


def test_pdf_upload_uses_only_fastapi_document_endpoint() -> None:
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["content_type"] = request.headers["content-type"]
        return httpx.Response(201, json={"document": {"id": "doc-1"}})

    client = client_for(httpx.MockTransport(handle))

    response = client.upload_document("policy.pdf", b"%PDF-safe")

    assert response["document"]["id"] == "doc-1"
    assert captured["path"] == "/api/v1/documents"
    assert str(captured["content_type"]).startswith("multipart/form-data")


def test_pdf_upload_is_bounded_before_http() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(201, json={})

    client = StudentSuccessAPIClient(
        FrontendConfig(
            api_base_url="http://backend.test",
            request_timeout_seconds=5,
            max_upload_bytes=8,
        ),
        client=httpx.Client(
            transport=httpx.MockTransport(handle),
            base_url="http://backend.test",
        ),
    )

    with pytest.raises(FrontendAPIError, match="size limit"):
        client.upload_document("policy.pdf", b"123456789")

    assert calls == 0


def test_post_timeout_is_not_retried() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("provider internals", request=request)

    client = client_for(httpx.MockTransport(handle))

    with pytest.raises(FrontendAPIError, match="too long"):
        client.ask("Question", agentic=False)

    assert calls == 1


def test_malformed_backend_response_is_safe() -> None:
    client = client_for(
        httpx.MockTransport(lambda request: httpx.Response(200, text="private traceback"))
    )

    with pytest.raises(FrontendAPIError) as captured:
        client.system_status()

    assert "traceback" not in captured.value.safe_message


def test_frontend_configuration_rejects_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    userinfo = ":".join(("synthetic", "fixture"))
    authority = "@".join((userinfo, "backend.example.invalid"))
    monkeypatch.setenv("FASTAPI_BASE_URL", urlunsplit(("http", authority, "", "", "")))

    with pytest.raises(ValueError, match="credential-free"):
        FrontendConfig.from_environment()


def test_frontend_has_no_backend_or_secret_provider_imports() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("frontend").rglob("*.py")
    ).casefold()

    assert "from backend" not in sources
    assert "import backend" not in sources
    assert "gemini_api_key" not in sources
    assert "langfuse_secret_key" not in sources
    assert "database_url" not in sources
    assert "supabase" not in sources
