"""Database-backed fixed-window rate limiting with pseudonymous keys."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import text

from backend.core.config import Settings
from backend.database.manager import DatabaseManager


class RateLimitService:
    def __init__(self, database: DatabaseManager, settings: Settings) -> None:
        self.database = database
        self.window_seconds = settings.rate_limit_window_seconds
        secret = settings.rate_limit_secret
        self._secret = (
            secret.get_secret_value().encode()
            if secret is not None
            else b"local-testing-rate-limit-key"
        )
        self.enabled = settings.environment.value != "testing"

    def identity_hash(self, identity: str) -> str:
        return hmac.new(self._secret, identity.encode(), sha256).hexdigest()

    async def allow(self, *, identity: str, bucket: str, limit: int) -> bool:
        if not self.enabled:
            return True
        now = datetime.now(UTC)
        window_epoch = int(now.timestamp()) // self.window_seconds * self.window_seconds
        window = datetime.fromtimestamp(window_epoch, tz=UTC)
        expiry = window + timedelta(seconds=self.window_seconds * 2)
        statement = text(
            "INSERT INTO rate_limit_counters "
            "(identity_hash, route_bucket, window_started_at, request_count, expires_at) "
            "VALUES (:identity, :bucket, :window, 1, :expiry) "
            "ON CONFLICT (identity_hash, route_bucket, window_started_at) DO UPDATE "
            "SET request_count = rate_limit_counters.request_count + 1 "
            "RETURNING request_count"
        )
        async with self.database.session() as session, session.begin():
            await session.execute(
                text("DELETE FROM rate_limit_counters WHERE expires_at <= :now"),
                {"now": now},
            )
            count = await session.scalar(
                statement,
                {
                    "identity": self.identity_hash(identity),
                    "bucket": bucket,
                    "window": window,
                    "expiry": expiry,
                },
            )
        return bool(count is not None and count <= limit)
