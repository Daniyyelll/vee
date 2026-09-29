import uuid

import asyncpg
from fastapi import APIRouter, Depends, status, Response
from starlette.responses import Response

from app.api.dependencies import is_admin
from app.core.exceptions import APIException
from app.db.session import get_connection
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.response import APIResponse
from app.services.category import (
    create_category,
    get_all_categories,
    update_category,
    delete_category,
)

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", status_code=status.HTTP_200_OK)
async def get_categories(
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[CategoryRead]]:
    categories = await get_all_categories(db)
    return APIResponse(
        status_code=status.HTTP_200_OK,
        message="Returned Categories",
        data=categories,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_category(
    body_data: CategoryCreate,
    db: asyncpg.Connection = Depends(get_connection),
    admin=Depends(is_admin),
) -> APIResponse:
    category_data = await create_category(db, body_data)

    return APIResponse(
        status_code=status.HTTP_201_CREATED,
        message="Category Created",
        data=category_data,
    )


@router.patch(
    "/{category_id}",
    response_model=APIResponse[CategoryRead],
    status_code=status.HTTP_200_OK,
)
async def edit_category(
    category_id: uuid.UUID,
    body_data: CategoryUpdate,
    db: asyncpg.Connection = Depends(get_connection),
    _: dict = Depends(is_admin),
) -> APIResponse[CategoryRead]:
    category = await update_category(db, category_id, body_data)

    return APIResponse(
        status_code=status.HTTP_200_OK,
        message="Category Updated",
        data=category,
    )


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_category(
    category_id: uuid.UUID,
    db: asyncpg.Connection = Depends(get_connection),
    admin=Depends(is_admin),
) -> Response:
    await delete_category(db=db, category_id=category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
