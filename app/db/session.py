"""Asyncpg connection-pool lifecycle and FastAPI dependencies."""

from collections.abc import AsyncIterator

import asyncpg
from fastapi import Depends

from app.core.config import settings

DatabasePool = asyncpg.Pool

_pool: DatabasePool | None = None


async def connect_database() -> None:
    """Create the process-wide pool during application startup."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.ASYNCPG_DATABASE_URL,
        min_size=1,
        max_size=10,
        timeout=settings.database_connect_timeout,
        command_timeout=settings.database_command_timeout,
        server_settings={
            "timezone": "UTC",
            "statement_timeout": str(settings.database_statement_timeout_ms),
        },
    )


async def disconnect_database() -> None:
    """Close idle and active connections during application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> DatabasePool:
    if _pool is None:
        raise RuntimeError("Database pool has not been initialized")
    return _pool


async def get_connection(
    pool: DatabasePool = Depends(get_pool),
) -> AsyncIterator[asyncpg.Connection]:
    """Acquire one pooled connection for the lifetime of a request."""
    async with pool.acquire(timeout=settings.database_acquire_timeout) as connection:
        yield connection
