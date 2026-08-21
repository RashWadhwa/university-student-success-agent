"""Non-secret frontend configuration."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class FrontendConfig:
    api_base_url: str
    request_timeout_seconds: float
    max_upload_bytes: int = 10 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> "FrontendConfig":
        base_url = os.getenv("FASTAPI_BASE_URL", "http://localhost:8000").rstrip("/")
        if "://" not in base_url:
            # Render's fromService.hostport is a private-network host:port value.
            base_url = f"http://{base_url}"
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("FASTAPI_BASE_URL must be a credential-free HTTP(S) URL")
        timeout = float(os.getenv("FRONTEND_REQUEST_TIMEOUT_SECONDS", "30"))
        if not 1 <= timeout <= 120:
            raise ValueError("FRONTEND_REQUEST_TIMEOUT_SECONDS must be between 1 and 120")
        max_upload_bytes = int(os.getenv("FRONTEND_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
        if not 1024 <= max_upload_bytes <= 100 * 1024 * 1024:
            raise ValueError("FRONTEND_MAX_UPLOAD_BYTES is outside the allowed range")
        return cls(
            api_base_url=base_url,
            request_timeout_seconds=timeout,
            max_upload_bytes=max_upload_bytes,
        )
