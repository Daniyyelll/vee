"""Verified-purchase reviews and ownership checks."""

from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.domain.enums import UserRole
from app.schemas.review import ReviewCreate, ReviewResponse, ReviewUpdate

REVIEW_COLUMNS = "id, rating, comment, username, created_at, product_id, user_id"


async def list_reviews(
    db: asyncpg.Connection, product_id: UUID, limit: int = 50, offset: int = 0
) -> list[ReviewResponse]:
    if not await db.fetchval(
        "SELECT EXISTS(SELECT 1 FROM product WHERE id = $1)", product_id
    ):
        raise APIException("Product not found.", status.HTTP_404_NOT_FOUND)
    rows = await db.fetch(
        f"""
        SELECT {REVIEW_COLUMNS} FROM review WHERE product_id = $1
        ORDER BY created_at DESC, id DESC LIMIT $2 OFFSET $3
        """,
        product_id,
        limit,
        offset,
    )
    return [ReviewResponse.model_validate(dict(row)) for row in rows]


async def _mark_reviewed(db, user_id: UUID, product_id: UUID, reviewed: bool):
    await db.execute(
        """
        UPDATE order_item oi SET is_reviewed = $3 FROM "order" o
        WHERE oi.order_id = o.id AND o.user_id = $1 AND oi.product_id = $2
        """,
        user_id,
        product_id,
        reviewed,
    )


async def create_review(
    db: asyncpg.Connection, user: dict[str, Any], request: ReviewCreate
) -> ReviewResponse:
    try:
        async with db.transaction():
            # Serialize review creation/deletion and checkout for this user.
            # Checkout takes this user lock before cart and product locks.
            await db.execute(
                'SELECT id FROM "user" WHERE id = $1 FOR UPDATE', user["id"]
            )
            if not await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM product WHERE id = $1)", request.product_id
            ):
                raise APIException("Product not found.", status.HTTP_404_NOT_FOUND)
            purchased = await db.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM order_item oi JOIN "order" o ON o.id = oi.order_id
                    WHERE o.user_id = $1 AND oi.product_id = $2
                      AND o.status = 'DELIVERED'
                )
                """,
                user["id"],
                request.product_id,
            )
            if not purchased:
                raise APIException(
                    "Reviews require a delivered purchase.", status.HTTP_403_FORBIDDEN
                )
            row = await db.fetchrow(
                f"""
                INSERT INTO review (id, rating, comment, username, product_id, user_id)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING {REVIEW_COLUMNS}
                """,
                uuid4(),
                request.rating,
                request.comment,
                user["name"],
                request.product_id,
                user["id"],
            )
            await _mark_reviewed(db, user["id"], request.product_id, True)
    except asyncpg.UniqueViolationError as exc:
        raise APIException(
            "You have already reviewed this product.", status.HTTP_409_CONFLICT
        ) from exc
    return ReviewResponse.model_validate(dict(row))


async def update_review(
    db: asyncpg.Connection, user_id: UUID, review_id: UUID, request: ReviewUpdate
) -> ReviewResponse:
    row = await db.fetchrow(
        f"""
        UPDATE review SET rating = COALESCE($3::integer, rating),
                          comment = COALESCE($4::text, comment)
        WHERE id = $1 AND user_id = $2 RETURNING {REVIEW_COLUMNS}
        """,
        review_id,
        user_id,
        request.rating,
        request.comment,
    )
    if row is None:
        raise APIException("Review not found.", status.HTTP_404_NOT_FOUND)
    return ReviewResponse.model_validate(dict(row))


async def delete_review(db: asyncpg.Connection, user: dict[str, Any], review_id: UUID):
    async with db.transaction():
        # Read the owner, lock their user row, then delete the review. All review
        # mutations that affect is_reviewed follow this same lock order.
        owner = await db.fetchval("SELECT user_id FROM review WHERE id = $1", review_id)
        if owner is None or (owner != user["id"] and user["role"] != UserRole.ADMIN):
            raise APIException("Review not found.", status.HTTP_404_NOT_FOUND)
        await db.execute('SELECT id FROM "user" WHERE id = $1 FOR UPDATE', owner)
        row = await db.fetchrow(
            "DELETE FROM review WHERE id = $1 RETURNING product_id", review_id
        )
        if row is None:
            raise APIException("Review not found.", status.HTTP_404_NOT_FOUND)
        await _mark_reviewed(db, owner, row["product_id"], False)
