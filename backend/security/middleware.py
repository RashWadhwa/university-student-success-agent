"""Bound request bodies and attach production-safe response headers."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.context import get_request_id


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, maximum_body_bytes: int, production: bool) -> None:
        self.app = app
        self.maximum_body_bytes = maximum_body_bytes
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                content_length = int(raw_length)
                too_large = content_length < 0 or content_length > self.maximum_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "The request body is too large.",
                        },
                        "request_id": get_request_id(),
                    },
                )
                await response(scope, receive, send)
                return

        received = 0

        async def receive_bounded() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.maximum_body_bytes:
                    raise RequestBodyTooLarge
            return message

        async def send_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(
                    [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    ]
                )
                path = str(scope.get("path", ""))
                if path.startswith(("/api/v1/auth", "/api/v1/memory", "/api/v1/audit")):
                    response_headers.append((b"cache-control", b"no-store"))
                if self.production:
                    response_headers.extend(
                        [
                            (
                                b"strict-transport-security",
                                b"max-age=31536000; includeSubDomains",
                            ),
                            (
                                b"content-security-policy",
                                b"default-src 'none'; frame-ancestors 'none'",
                            ),
                        ]
                    )
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive_bounded, send_headers)
        except RequestBodyTooLarge:
            response = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "The request body is too large.",
                    },
                    "request_id": get_request_id(),
                },
            )
            await response(scope, receive, send_headers)


class RequestBodyTooLarge(Exception):
    """Internal flow control; never exposed with implementation details."""
