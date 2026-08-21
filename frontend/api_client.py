"""Single safe HTTP boundary between Streamlit and FastAPI."""

from __future__ import annotations

from typing import Any

import httpx

from frontend.config import FrontendConfig

_SAFE_MESSAGES = {
    400: "The request could not be processed.",
    404: "The requested service was not found.",
    409: "This document has already been uploaded.",
    413: "The uploaded document is too large.",
    422: "Please check the submitted fields and try again.",
    429: "The service is busy. Please wait before trying again.",
    500: "The service encountered an unexpected problem.",
    502: "An optional provider returned an invalid response.",
    503: "The requested service is temporarily unavailable.",
    504: "The request timed out.",
}


class FrontendAPIError(RuntimeError):
    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        super().__init__(message)
        self.safe_message = message
        self.request_id = request_id


class StudentSuccessAPIClient:
    def __init__(
        self,
        config: FrontendConfig,
        *,
        client: httpx.Client | None = None,
        access_token: str | None = None,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self._access_token = access_token
        self._client = client or httpx.Client(
            base_url=config.api_base_url,
            timeout=httpx.Timeout(config.request_timeout_seconds, connect=5.0),
            follow_redirects=False,
        )

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", retry_read=True)

    def ready(self) -> dict[str, Any]:
        return self._request("GET", "/ready", retry_read=True)

    def system_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/system/status", retry_read=True)

    def public_config(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/config/public", retry_read=True)

    def current_user(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/auth/me", retry_read=True)

    def ask(
        self,
        question: str,
        *,
        agentic: bool,
        top_k: int = 5,
    ) -> dict[str, Any]:
        endpoint = "/api/v1/ask/agentic" if agentic else "/api/v1/ask"
        return self._request(
            "POST",
            endpoint,
            json={"question": question, "top_k": top_k, "filters": {}},
        )

    def upload_document(self, filename: str, content: bytes) -> dict[str, Any]:
        if not content:
            raise FrontendAPIError("The selected document is empty.")
        if len(content) > self.config.max_upload_bytes:
            raise FrontendAPIError("The selected document exceeds the upload size limit.")
        return self._request(
            "POST",
            "/api/v1/documents",
            files={"file": (filename, content, "application/pdf")},
        )

    def index_document(self, document_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/documents/{document_id}/index",
            json=metadata,
        )

    def retrieval_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/retrieval/search",
            json={
                "query": query,
                "top_k": top_k,
                "minimum_score": 0.0,
                "prefer_recent": True,
                "filters": filters or {},
            },
        )

    def evaluation_datasets(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/evaluations/datasets", retry_read=True)

    def run_evaluation(self, *, dataset: str, workflow: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/evaluations/run",
            json={"dataset": dataset, "workflow": workflow},
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, *, retry_read: bool = False, **kwargs: Any) -> Any:
        if self._access_token:
            headers = dict(kwargs.pop("headers", {}))
            headers["Authorization"] = f"Bearer {self._access_token}"
            kwargs["headers"] = headers
        attempts = 2 if retry_read and method == "GET" else 1
        response: httpx.Response | None = None
        try:
            for attempt in range(attempts):
                try:
                    response = self._client.request(method, path, **kwargs)
                    break
                except httpx.TimeoutException:
                    if attempt + 1 == attempts:
                        raise
            if response is None:
                raise FrontendAPIError("The backend is unavailable.")
            if response.is_error:
                request_id = response.headers.get("x-request-id")
                message = _SAFE_MESSAGES.get(
                    response.status_code,
                    "The request could not be completed safely.",
                )
                raise FrontendAPIError(message, request_id=request_id)
            payload = response.json()
            if not isinstance(payload, dict):
                raise FrontendAPIError("The backend returned an unexpected response.")
            return payload
        except httpx.TimeoutException as exc:
            raise FrontendAPIError("The backend took too long to respond.") from exc
        except httpx.RequestError as exc:
            raise FrontendAPIError("The backend is unavailable.") from exc
        except ValueError as exc:
            raise FrontendAPIError("The backend returned an unexpected response.") from exc
