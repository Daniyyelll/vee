"""MFA enrollment and verification for administrator and delivery accounts."""

import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.core.security import create_access_token, create_token, decode_token
from app.domain.enums import UserRole
from app.schemas.user import (
    StaffMFAEnrollment,
    StaffMFAVerifyRequest,
    TokenData,
    UserLogin,
    UserRead,
)
from app.services.mfa import (
    decrypt_secret,
    encrypt_secret,
    generate_secret,
    provisioning_uri,
    verify_code,
)
from app.services.user import password_hasher, user_to_dict

STAFF_ROLES = {UserRole.ADMIN, UserRole.DELIVERY}


async def verify_staff_login_mfa(
    db: asyncpg.Connection, login_data: UserLogin, user: UserRead
) -> None:
    if user.role not in STAFF_ROLES:
        return
    row = await db.fetchrow(
        """
        SELECT staff_mfa_secret, staff_mfa_enabled, staff_mfa_last_counter
        FROM "user" WHERE id = $1 FOR UPDATE
        """,
        user.id,
    )
    if row is None or not row["staff_mfa_enabled"]:
        raise APIException(
            "Staff MFA enrollment is required.", status.HTTP_403_FORBIDDEN
        )
    secret = decrypt_secret(row["staff_mfa_secret"])
    counter = (
        verify_code(
            secret,
            login_data.mfa_code or "",
            last_counter=row["staff_mfa_last_counter"],
        )
        if secret
        else None
    )
    if counter is None:
        raise APIException(
            "Invalid email, password, or MFA code.",
            status.HTTP_401_UNAUTHORIZED,
        )
    updated = await db.execute(
        'UPDATE "user" SET staff_mfa_last_counter = $1 WHERE id = $2 '
        "AND (staff_mfa_last_counter IS NULL OR staff_mfa_last_counter < $1)",
        counter,
        user.id,
    )
    if updated != "UPDATE 1":
        raise APIException(
            "MFA code has already been used.", status.HTTP_401_UNAUTHORIZED
        )


async def begin_staff_mfa_enrollment(
    db: asyncpg.Connection, email: str, password: str
) -> StaffMFAEnrollment:
    row = await db.fetchrow(
        """
        SELECT id, email, hashed_password, role::text AS role, active,
               token_version, staff_mfa_enabled
        FROM "user" WHERE lower(email) = $1 FOR UPDATE
        """,
        email.lower(),
    )
    valid = (
        row is not None
        and password_hasher.verify(password, row["hashed_password"])
        and row["active"]
        and UserRole(row["role"].lower()) in STAFF_ROLES
    )
    if not valid:
        raise APIException("Invalid staff credentials.", status.HTTP_401_UNAUTHORIZED)
    if row["staff_mfa_enabled"]:
        raise APIException("Staff MFA is already enabled.", status.HTTP_409_CONFLICT)

    secret = generate_secret()
    await db.execute(
        'UPDATE "user" SET staff_mfa_secret = $1, '
        "staff_mfa_pending_expires_at = NOW() + INTERVAL '10 minutes' "
        "WHERE id = $2",
        encrypt_secret(secret),
        row["id"],
    )
    token = create_token(
        {"sub": str(row["id"]), "ver": row["token_version"]},
        token_type="mfa_enrollment",
        expires_in=timedelta(minutes=10),
    )
    return StaffMFAEnrollment(
        secret=secret,
        provisioning_uri=provisioning_uri(secret, row["email"]),
        enrollment_token=token,
    )


async def verify_staff_mfa_enrollment(
    db: asyncpg.Connection, request: StaffMFAVerifyRequest
) -> TokenData:
    payload = decode_token(request.enrollment_token, token_type="mfa_enrollment")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise APIException(
            "Invalid enrollment token.", status.HTTP_401_UNAUTHORIZED
        ) from exc

    row = await db.fetchrow(
        """
        SELECT id, name, email, role::text AS role, active, address, phone,
               token_version, staff_mfa_secret, staff_mfa_enabled,
               staff_mfa_pending_expires_at, staff_mfa_last_counter
        FROM "user" WHERE id = $1 FOR UPDATE
        """,
        user_id,
    )
    if (
        row is None
        or not row["active"]
        or row["staff_mfa_enabled"]
        or payload.get("ver") != row["token_version"]
        or row["staff_mfa_pending_expires_at"] is None
        or row["staff_mfa_pending_expires_at"] <= datetime.now(timezone.utc)
    ):
        raise APIException("Invalid enrollment token.", status.HTTP_401_UNAUTHORIZED)

    secret = decrypt_secret(row["staff_mfa_secret"])
    counter = verify_code(
        secret or "", request.code, last_counter=row["staff_mfa_last_counter"]
    )
    if counter is None:
        raise APIException("Invalid MFA code.", status.HTTP_401_UNAUTHORIZED)

    await db.execute(
        'UPDATE "user" SET staff_mfa_enabled = TRUE, '
        "staff_mfa_last_counter = $1, staff_mfa_pending_expires_at = NULL "
        "WHERE id = $2",
        counter,
        user_id,
    )
    user = user_to_dict(row)
    return TokenData(
        token=create_access_token(
            {
                "sub": str(user["id"]),
                "role": user["role"].value,
                "ver": user["token_version"],
            }
        ),
        user=user,
    )
