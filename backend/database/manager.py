"""Async SQLAlchemy engine, sessions, and lightweight readiness checks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    """Safe database readiness result without connection details."""

    database: bool
    pgvector: bool


def normalise_async_database_url(database_url: str) -> str:
    """Normalise ordinary PostgreSQL/Supabase URLs for SQLAlchemy asyncpg."""

    url = make_url(database_url)
    if not url.drivername.startswith("postgresql") and url.drivername != "postgres":
        raise ValueError("DATABASE_URL must use PostgreSQL")
    query = dict(url.query)
    if "sslmode" in query and "ssl" not in query:
        query["ssl"] = query.pop("sslmode")
    return url.set(drivername="postgresql+asyncpg", query=query).render_as_string(
        hide_password=False
    )


class DatabaseManager:
    """Own the async engine and provide transaction-scoped sessions."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int,
        max_overflow: int,
        pool_timeout: float,
        readiness_timeout: float = 3.0,
        engine: AsyncEngine | None = None,
    ) -> None:
        self.engine = engine or create_async_engine(
            normalise_async_database_url(database_url),
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self.readiness_timeout = readiness_timeout

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield one session; callers explicitly own transaction boundaries."""

        async with self.session_factory() as session:
            yield session

    async def check_readiness(self) -> DatabaseReadiness:
        """Check connectivity and extension presence without embeddings or writes."""

        try:
            async with asyncio.timeout(self.readiness_timeout):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                    vector_enabled = bool(
                        await connection.scalar(
                            text(
                                "SELECT EXISTS (SELECT 1 FROM pg_extension "
                                "WHERE extname = 'vector')"
                            )
                        )
                    )
            return DatabaseReadiness(database=True, pgvector=vector_enabled)
        except (SQLAlchemyError, TimeoutError) as exc:
            logger.warning(
                "Database readiness check failed",
                extra={"error_type": type(exc).__name__},
            )
            return DatabaseReadiness(database=False, pgvector=False)

    async def close(self) -> None:
        """Release pooled database connections."""

        await self.engine.dispose()
