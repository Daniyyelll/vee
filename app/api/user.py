import asyncpg
from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_user
from app.db.session import get_connection
from app.schemas.response import APIResponse
from app.schemas.user import PasswordUpdate, UserRead, UserUpdate
from app.services.user import update_user_password, update_user_profile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_my_profile(
    current_user=Depends(get_current_user),
) -> APIResponse[UserRead]:
    return APIResponse[UserRead](
        status_code=status.HTTP_200_OK,
        message="You have been logged in",
        data=current_user,
    )


@router.patch("/update-profile", status_code=status.HTTP_200_OK)
async def update_profile(
    body_data: UserUpdate,
    current_user=Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
):

    updated_user = await update_user_profile(db, current_user, body_data)

    return APIResponse[UserRead](
        status_code=status.HTTP_200_OK,
        message="Profile was updated successfully",
        data=updated_user,
    )


@router.patch("/change-password", status_code=status.HTTP_200_OK)
async def update_password(
    body_data: PasswordUpdate,
    current_user=Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
):
    await update_user_password(db, current_user, body_data)
    return APIResponse[PasswordUpdate](
        status_code=status.HTTP_200_OK,
        message="Password was updated successfully",
    )
