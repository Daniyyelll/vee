from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_current_user, is_admin
from app.db.session import get_connection
from app.schemas.response import APIResponse
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewUpdate
from app.services.audit import record_audit
from app.services.review import (
    create_review,
    delete_review,
    get_review,
    list_reviews,
    update_review,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("")
async def show_reviews(
    product_id: UUID = Query(alias="productId"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[ReviewResponse]]:
    reviews = await list_reviews(db, product_id, limit, offset)
    return APIResponse(status_code=200, message="Reviews", data=reviews)


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_review(
    request: ReviewCreate,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ReviewResponse]:
    review = await create_review(db, user, request)
    return APIResponse(status_code=201, message="Review created", data=review)


@router.get("/{review_id}")
async def show_review(
    review_id: UUID,
    _admin: dict[str, Any] = Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ReviewResponse]:
    review = await get_review(db, review_id)
    return APIResponse(status_code=200, message="Review", data=review)


@router.patch("/{review_id}")
async def edit_review(
    review_id: UUID,
    request: ReviewUpdate,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ReviewResponse]:
    review = await update_review(db, user["id"], review_id, request)
    return APIResponse(status_code=200, message="Review updated", data=review)


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_review(
    review_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> Response:
    async with db.transaction():
        await delete_review(db, user, review_id)
        await record_audit(db, user, "review.deleted", "review", review_id)
    return Response(status_code=204)
