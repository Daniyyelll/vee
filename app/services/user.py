"""User workflows implemented with parameterized PostgreSQL queries."""

import secrets
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import asyncpg
from fastapi import status
from pwdlib import PasswordHash

from app.core.config import settings
from app.core.exceptions import APIException
from app.core.security import create_access_token
from app.domain.enums import UserRole
from app.schemas.user import (
    PasswordUpdate,
    ResetPasswordRequest,
    TokenData,
    UserCreate,
    UserLogin,
    UserUpdate,
)
from app.services.outbox import enqueue_email
from app.services.rate_limit import consume_rate_limit

password_hasher = PasswordHash.recommended()

USER_COLUMNS = """
    id, name, email, role::text AS role, active, address, phone, token_version
"""


def user_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert PostgreSQL enum storage to the API enum's lowercase value."""
    data = dict(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": UserRole(row["role"].lower()),
        "active": row["active"],
        "address": row["address"],
        "phone": data.get("phone"),
        "token_version": data.get("token_version", 0),
    }


async def register_user(
    connection: asyncpg.Connection, user_data: UserCreate
) -> dict[str, Any]:
    """Create a user, allowing the unique database index to resolve races."""
    if user_data.role not in (None, UserRole.CUSTOMER):
        raise APIException(
            "Public registration can only create customer accounts.",
            status.HTTP_403_FORBIDDEN,
        )
    try:
        row = await connection.fetchrow(
            f"""
            INSERT INTO "user" (id, name, email, hashed_password, phone, role, active)
            VALUES ($1, $2, $3, $4, $5, $6, TRUE)
            RETURNING {USER_COLUMNS}
            """,
            uuid.uuid4(),
            user_data.name,
            str(user_data.email),
            password_hasher.hash(user_data.password),
            user_data.phone,
            (user_data.role or UserRole.CUSTOMER).name,
        )
    except asyncpg.UniqueViolationError as exc:
        raise APIException(
            message="A user with this email already exists.",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc

    return user_to_dict(row)


async def login_user(
    connection: asyncpg.Connection, login_data: UserLogin
) -> TokenData:
    await consume_rate_limit(
        connection,
        "login-email",
        str(login_data.email),
        limit=10,
        window_seconds=900,
    )
    row = await connection.fetchrow(
        """
        SELECT id, name, email, hashed_password, role::text AS role, active,
               address, phone, token_version
        FROM "user"
        WHERE lower(email) = $1
        """,
        str(login_data.email),
    )

    if row is None or not password_hasher.verify(
        login_data.password, row["hashed_password"]
    ):
        raise APIException(
            message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if not row["active"]:
        raise APIException(
            message="This account is inactive.", status_code=status.HTTP_403_FORBIDDEN
        )

    await connection.execute(
        'UPDATE "user" SET last_login = NOW() WHERE id = $1', row["id"]
    )

    user = user_to_dict(row)

    return TokenData(
        token=create_access_token(
            claims={
                "sub": str(user["id"]),
                "role": user["role"].value,
                "ver": user["token_version"],
                "iat": datetime.now(timezone.utc),
            }
        ),
        user=user,
    )


async def process_forgot_password(connection: asyncpg.Connection, email: str) -> bool:
    await consume_rate_limit(
        connection, "forgot-email", email, limit=3, window_seconds=3600
    )
    row = await connection.fetchrow(
        'SELECT name, email FROM "user" WHERE lower(email) = $1', email.lower()
    )
    if row is None:
        return True

    token = secrets.token_urlsafe(32)
    reset_url = f"{settings.RESET_PASSWORD_URL}{token}"
    async with connection.transaction():
        await connection.execute(
            "INSERT INTO reset_code (id, email, code) VALUES ($1, $2, $3)",
            uuid.uuid4(),
            row["email"],
            sha256(token.encode()).hexdigest(),
        )
        await enqueue_email(
            connection,
            "password_reset",
            {
                "email": row["email"],
                "name": row["name"],
                "token": token,
                "reset_url": reset_url,
            },
        )
    return True


async def process_reset_password(
    connection: asyncpg.Connection, reset_data: ResetPasswordRequest
) -> bool:
    """Consume one valid reset code and change the password atomically."""
    async with connection.transaction():
        reset_code = await connection.fetchrow(
            """
            SELECT id, email, expires_at
            FROM reset_code
            WHERE code = $1
            FOR UPDATE
            """,
            sha256(reset_data.code.encode()).hexdigest(),
        )
        if reset_code is None or datetime.now(timezone.utc) > reset_code["expires_at"]:
            raise APIException(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Reset code is invalid or expired.",
            )

        updated = await connection.execute(
            'UPDATE "user" SET hashed_password = $1, '
            "token_version = token_version + 1 WHERE email = $2",
            password_hasher.hash(reset_data.new_password),
            reset_code["email"],
        )
        if updated == "UPDATE 0":
            raise APIException(
                status_code=status.HTTP_401_UNAUTHORIZED, message="User not found."
            )

        await connection.execute(
            "DELETE FROM reset_code WHERE email = $1", reset_code["email"]
        )

    return True


PROFILE_COLUMNS = {
    "name": "name",
    "address": "address",
    "phone": "phone",
}


async def update_user_profile(
    db: asyncpg.Connection, user: dict[str, Any], update_data: UserUpdate
) -> dict[str, Any]:
    changes = update_data.model_dump(exclude_unset=True)

    if not changes:
        raise APIException(
            "Provide at least one profile field.", status.HTTP_400_BAD_REQUEST
        )
    if "name" in changes and changes["name"] is None:
        raise APIException("Name cannot be null.", status.HTTP_400_BAD_REQUEST)

    assignments: list[str] = []
    values: list[object] = []

    for field, value in changes.items():
        column = PROFILE_COLUMNS.get(field)
        if column is None:
            continue

        values.append(value)
        assignments.append(f"{column} = ${len(values)}")

    if not assignments:
        raise APIException(
            "Provide at least one profile field.", status.HTTP_400_BAD_REQUEST
        )

    values.append(user.get("id"))

    row = await db.fetchrow(
        f"""
        UPDATE "user"
        SET {", ".join(assignments)}
        WHERE id = ${len(values)}
        RETURNING {USER_COLUMNS}
        """,
        *values,
    )

    if row is None:
        raise APIException("User not found.", status_code=status.HTTP_404_NOT_FOUND)

    return user_to_dict(row)


async def update_user_password(
    db: asyncpg.Connection, user, update_data: PasswordUpdate
) -> None:
    current_hash = await db.fetchval(
        'SELECT hashed_password FROM "user" WHERE id = $1',
        user.get("id"),
    )

    if current_hash is None or not password_hasher.verify(
        update_data.old_password, current_hash
    ):
        raise APIException(
            message="Invalid current password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if password_hasher.verify(update_data.new_password, current_hash):
        raise APIException(
            message="New password must differ from the current password.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    result = await db.execute(
        """
        UPDATE "user"
        SET hashed_password = $1, token_version = token_version + 1
        WHERE id = $2
          AND hashed_password = $3
        """,
        password_hasher.hash(update_data.new_password),
        user.get("id"),
        current_hash,
    )

    if result != "UPDATE 1":
        raise APIException(
            message="Password changed concurrently. Please try again.",
            status_code=status.HTTP_409_CONFLICT,
        )
