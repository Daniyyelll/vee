import uuid

import asyncpg
from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import is_admin
from app.db.session import get_connection
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.schemas.response import APIResponse
from app.services.audit import record_audit
from app.services.category import (
    create_category,
    delete_category,
    get_all_categories,
    update_category,
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
    async with db.transaction():
        category_data = await create_category(db, body_data)
        await record_audit(
            db, admin, "category.created", "category", category_data["id"]
        )

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
    admin: dict = Depends(is_admin),
) -> APIResponse[CategoryRead]:
    async with db.transaction():
        category = await update_category(db, category_id, body_data)
        await record_audit(db, admin, "category.updated", "category", category_id)

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
    async with db.transaction():
        await delete_category(db=db, category_id=category_id)
        await record_audit(db, admin, "category.deleted", "category", category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
