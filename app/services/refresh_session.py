"""Opaque refresh tokens; only SHA-256 digests are persisted."""

import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.core.security import create_access_token
from app.services.user import user_to_dict

REFRESH_SESSION_DAYS = 14


def _digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(48)


async def create_refresh_session(
    db: asyncpg.Connection, user_id: UUID, token_version: int
) -> tuple[str, datetime]:
    token = _new_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_SESSION_DAYS)
    await db.execute(
        """
        INSERT INTO refresh_session (id, user_id, token_hash, token_version, expires_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        uuid4(),
        user_id,
        _digest(token),
        token_version,
        expires_at,
    )
    return token, expires_at


async def rotate_refresh_session(
    db: asyncpg.Connection, token: str
) -> tuple[str, datetime, str, dict]:
    replacement = _new_token()
    row = await db.fetchrow(
        """
        UPDATE refresh_session AS session
        SET token_hash = $2, last_used_at = NOW()
        FROM "user" AS account
        WHERE session.token_hash = $1
          AND session.user_id = account.id
          AND session.expires_at > NOW()
          AND session.token_version = account.token_version
          AND account.active = TRUE
        RETURNING session.expires_at,
                  account.id, account.name, account.email,
                  account.role::text AS role, account.active,
                  account.address, account.phone, account.token_version
        """,
        _digest(token),
        _digest(replacement),
    )
    if row is None:
        raise APIException(
            "Refresh session is invalid or expired.", status.HTTP_401_UNAUTHORIZED
        )
    user = user_to_dict(row)
    access_token = create_access_token(
        {
            "sub": str(user["id"]),
            "role": user["role"].value,
            "ver": user["token_version"],
            "iat": datetime.now(timezone.utc),
        }
    )
    return replacement, row["expires_at"], access_token, user


async def revoke_refresh_session(db: asyncpg.Connection, token: str) -> None:
    await db.execute(
        "DELETE FROM refresh_session WHERE token_hash = $1", _digest(token)
    )
