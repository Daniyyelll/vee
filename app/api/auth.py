import asyncpg
from fastapi import APIRouter, Depends, status

from app.db.session import get_connection
from app.schemas.response import APIResponse
from app.schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenData,
    UserCreate,
    UserLogin,
    UserRead,
)
from app.services.user import (
    login_user,
    process_forgot_password,
    process_reset_password,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


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
    login_data: UserLogin, db: asyncpg.Connection = Depends(get_connection)
) -> APIResponse[TokenData]:
    token_info = await login_user(db, login_data)

    return APIResponse(
        message="User Logged In Successfully",
        status_code=status.HTTP_200_OK,
        data=token_info,
    )


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
