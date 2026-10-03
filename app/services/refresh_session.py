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
    session_id = uuid4()
    await db.execute(
        """
        INSERT INTO refresh_session
            (id, user_id, token_hash, token_version, expires_at, family_id)
        VALUES ($1, $2, $3, $4, $5, $1)
        """,
        session_id,
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
    reuse_detected = False
    async with db.transaction():
        row = await db.fetchrow(
            """
            SELECT session.id AS session_id, session.family_id,
                   session.replaced_by_id, session.revoked_at,
                   session.expires_at,
                   account.id, account.name, account.email,
                   account.role::text AS role, account.active,
                   account.address, account.phone, account.token_version,
                   session.token_version AS session_token_version
            FROM refresh_session AS session
            JOIN "user" AS account ON account.id = session.user_id
            WHERE session.token_hash = $1
            FOR UPDATE OF session, account
            """,
            _digest(token),
        )
        if row is None:
            raise APIException(
                "Refresh session is invalid or expired.",
                status.HTTP_401_UNAUTHORIZED,
            )

        reused = row["replaced_by_id"] is not None or row["revoked_at"] is not None
        if reused:
            await db.execute(
                "UPDATE refresh_session SET revoked_at = COALESCE(revoked_at, NOW()) "
                "WHERE family_id = $1",
                row["family_id"],
            )
            await db.execute(
                'UPDATE "user" SET token_version = token_version + 1 WHERE id = $1',
                row["id"],
            )
            reuse_detected = True
        else:
            if (
                row["expires_at"] <= datetime.now(timezone.utc)
                or not row["active"]
                or row["session_token_version"] != row["token_version"]
            ):
                raise APIException(
                    "Refresh session is invalid or expired.",
                    status.HTTP_401_UNAUTHORIZED,
                )

            replacement_id = uuid4()
            await db.execute(
                """
                INSERT INTO refresh_session
                    (id, user_id, token_hash, token_version, expires_at, family_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                replacement_id,
                row["id"],
                _digest(replacement),
                row["token_version"],
                row["expires_at"],
                row["family_id"],
            )
            await db.execute(
                "UPDATE refresh_session SET replaced_by_id = $1, "
                "last_used_at = NOW() WHERE id = $2",
                replacement_id,
                row["session_id"],
            )
    if reuse_detected:
        raise APIException(
            "Refresh token reuse was detected. Sign in again.",
            status.HTTP_401_UNAUTHORIZED,
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
        """
        UPDATE refresh_session SET revoked_at = COALESCE(revoked_at, NOW())
        WHERE family_id = (
            SELECT family_id FROM refresh_session WHERE token_hash = $1
        )
        """,
        _digest(token),
    )
