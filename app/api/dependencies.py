import uuid
from typing import Any

import asyncpg
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import APIException
from app.core.security import decode_access_token
from app.db.session import get_connection
from app.domain.enums import UserRole
from app.services.user import user_to_dict

bearer_scheme = HTTPBearer()


async def get_current_user(
    db: asyncpg.Connection = Depends(get_connection),
    token: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict[str, Any]:
    payload = decode_access_token(token.credentials)

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise APIException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Could not validate credentials",
        ) from exc

    row = await db.fetchrow(
        """
        SELECT id, name, email, role::text AS role, active, address
        FROM "user"
        WHERE id = $1
        """,
        user_id,
    )

    if row is None or not row["active"]:
        raise APIException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Could not validate credentials",
        )

    return user_to_dict(row)


async def is_admin(current_user: dict[str, Any] = Depends(get_current_user)):
    if current_user["role"] != UserRole.ADMIN:
        raise APIException(
            status_code=status.HTTP_403_FORBIDDEN,
            message="You are not an administrator",
        )

    return current_user


async def is_delivery_or_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
):
    if current_user["role"] not in [UserRole.ADMIN, UserRole.DELIVERY]:
        raise APIException(
            status_code=status.HTTP_403_FORBIDDEN,
            message="You do not have permission",
        )

    return current_user
