"""Shared PostgreSQL rate limits for public and credential endpoints."""

import hmac
from hashlib import sha256

import asyncpg
from fastapi import status

from app.core.config import settings
from app.core.exceptions import APIException


async def consume_rate_limit(
    db: asyncpg.Connection,
    bucket: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    key = hmac.new(
        settings.secret_jwt_key.encode(),
        f"{bucket}:{identity.strip().lower()}".encode(),
        sha256,
    ).hexdigest()
    hits = await db.fetchval(
        """
        INSERT INTO rate_limit (key, hits, reset_at)
        VALUES ($1, 1, NOW() + $2 * INTERVAL '1 second')
        ON CONFLICT (key) DO UPDATE SET
            hits = CASE WHEN rate_limit.reset_at <= NOW() THEN 1
                        ELSE rate_limit.hits + 1 END,
            reset_at = CASE WHEN rate_limit.reset_at <= NOW()
                            THEN NOW() + $2 * INTERVAL '1 second'
                            ELSE rate_limit.reset_at END
        RETURNING hits
        """,
        key,
        window_seconds,
    )
    if hits > limit:
        raise APIException(
            "Too many requests. Try again later.", status.HTTP_429_TOO_MANY_REQUESTS
        )
