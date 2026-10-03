from datetime import datetime, timezone
from urllib.parse import urlsplit

import asyncpg
from fastapi import APIRouter, Depends, Request, Response, status

from app.core.config import settings
from app.core.exceptions import APIException
from app.db.session import get_connection
from app.schemas.response import APIResponse
from app.schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    StaffMFAEnrollment,
    StaffMFAEnrollRequest,
    StaffMFAVerifyRequest,
    TokenData,
    UserCreate,
    UserLogin,
    UserRead,
)
from app.services.audit import record_audit
from app.services.rate_limit import consume_rate_limit
from app.services.refresh_session import (
    create_refresh_session,
    revoke_refresh_session,
    rotate_refresh_session,
)
from app.services.staff_auth import (
    begin_staff_mfa_enrollment,
    verify_staff_login_mfa,
    verify_staff_mfa_enrollment,
)
from app.services.user import (
    limit_login_attempt,
    login_user,
    process_forgot_password,
    process_reset_password,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
REFRESH_COOKIE = "vee-refresh"
REFRESH_COOKIE_PATH = "/api/auth"


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    allowed = {_origin(settings.FRONTEND_URL), _origin(settings.BACKEND_URL)}
    if origin and origin not in allowed:
        raise APIException("Request origin is not allowed.", status.HTTP_403_FORBIDDEN)


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    remaining = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=remaining,
        path=REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        secure=settings.REFRESH_COOKIE_SECURE,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )
    response.headers["Cache-Control"] = "no-store"


@router.get("/health", status_code=status.HTTP_200_OK)
def health():
    return {"status": "Auth ok"}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate, db: asyncpg.Connection = Depends(get_connection)
) -> APIResponse[UserRead]:
    user = await register_user(db, user_data)
    return APIResponse(
        message="User Created", status_code=status.HTTP_201_CREATED, data=user
    )


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    login_data: UserLogin,
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[TokenData]:
    _check_origin(request)
    await limit_login_attempt(db, login_data)
    async with db.transaction():
        token_info = await login_user(db, login_data)
        await verify_staff_login_mfa(db, login_data, token_info.user)
        version = await db.fetchval(
            'SELECT token_version FROM "user" WHERE id = $1', token_info.user.id
        )
        refresh_token, expires_at = await create_refresh_session(
            db, token_info.user.id, version
        )
    _set_refresh_cookie(response, refresh_token, expires_at)

    return APIResponse(
        message="User Logged In Successfully",
        status_code=status.HTTP_200_OK,
        data=token_info,
    )


@router.post("/staff-mfa/enroll", status_code=status.HTTP_200_OK)
async def enroll_staff_mfa(
    body: StaffMFAEnrollRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[StaffMFAEnrollment]:
    _check_origin(request)
    await consume_rate_limit(
        db, "staff-mfa-enroll", str(body.email), limit=5, window_seconds=900
    )
    async with db.transaction():
        enrollment = await begin_staff_mfa_enrollment(
            db, str(body.email), body.password
        )
    return APIResponse(
        message="Verify the authenticator code to finish enrollment.",
        status_code=status.HTTP_200_OK,
        data=enrollment,
    )


@router.post("/staff-mfa/verify", status_code=status.HTTP_200_OK)
async def verify_staff_mfa(
    body: StaffMFAVerifyRequest,
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[TokenData]:
    _check_origin(request)
    async with db.transaction():
        token_info = await verify_staff_mfa_enrollment(db, body)
        version = await db.fetchval(
            'SELECT token_version FROM "user" WHERE id = $1', token_info.user.id
        )
        refresh_token, expires_at = await create_refresh_session(
            db, token_info.user.id, version
        )
        await record_audit(
            db,
            {"id": token_info.user.id},
            "staff.mfa_enabled",
            "user",
            token_info.user.id,
        )
    _set_refresh_cookie(response, refresh_token, expires_at)
    return APIResponse(
        message="Staff MFA enabled.",
        status_code=status.HTTP_200_OK,
        data=token_info,
    )


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[TokenData]:
    _check_origin(request)
    cookie = request.cookies.get(REFRESH_COOKIE)
    if not cookie:
        raise APIException(
            "No refresh session is available.", status.HTTP_401_UNAUTHORIZED
        )
    replacement, expires_at, access_token, user = await rotate_refresh_session(
        db, cookie
    )
    _set_refresh_cookie(response, replacement, expires_at)
    return APIResponse(
        status_code=200,
        message="Session refreshed",
        data=TokenData(token=access_token, user=user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: asyncpg.Connection = Depends(get_connection),
) -> None:
    _check_origin(request)
    cookie = request.cookies.get(REFRESH_COOKIE)
    if cookie:
        await revoke_refresh_session(db, cookie)
    _clear_refresh_cookie(response)


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    request: ForgotPasswordRequest, db: asyncpg.Connection = Depends(get_connection)
) -> APIResponse[None]:
    await process_forgot_password(db, request.email)

    return APIResponse[None](
        status_code=status.HTTP_202_ACCEPTED,
        message="If this account exists, a reset link will be sent.",
    )


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    reset_data: ResetPasswordRequest,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[None]:
    await process_reset_password(db, reset_data)
    return APIResponse(
        message="Password reset successfully", status_code=status.HTTP_200_OK
    )
