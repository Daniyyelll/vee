"""Coupon creation and serialized redemption inside checkout transactions."""

import secrets
import string
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.schemas.coupon import CouponCreate, CouponRead

ALPHABET = string.ascii_uppercase + string.digits


def normalize_code(code: str) -> str:
    value = code.strip().upper()
    if not (4 <= len(value) <= 64) or not all(
        character in ALPHABET + "-_" for character in value
    ):
        raise APIException("Coupon code must have 4-64 letters, digits, - or _.")
    return value


async def create_coupon(db: asyncpg.Connection, request: CouponCreate) -> CouponRead:
    if request.assigned_user_id is not None:
        exists = await db.fetchval(
            """SELECT EXISTS (
                SELECT 1 FROM "user" WHERE id = $1 AND role = 'CUSTOMER'
            )""",
            request.assigned_user_id,
        )
        if not exists:
            raise APIException(
                "Assigned customer not found.", status.HTTP_404_NOT_FOUND
            )
    for _ in range(5):
        code = (
            normalize_code(request.code)
            if request.code
            else "VEE-" + "".join(secrets.choice(ALPHABET) for _ in range(12))
        )
        try:
            row = await db.fetchrow(
                """
                INSERT INTO coupon (id, code, kind, discount_percent,
                    starts_at, expires_at, assigned_user_id, max_uses)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *, 0::bigint AS uses_count
                """,
                uuid4(),
                code,
                request.kind,
                request.discount_percent,
                request.starts_at,
                request.expires_at,
                request.assigned_user_id,
                request.max_uses,
            )
            return CouponRead.model_validate(dict(row))
        except asyncpg.UniqueViolationError as exc:
            if request.code:
                raise APIException(
                    "Coupon code already exists.", status.HTTP_409_CONFLICT
                ) from exc
    raise APIException(
        "Could not generate a unique coupon.", status.HTTP_503_SERVICE_UNAVAILABLE
    )


async def list_coupons(db: asyncpg.Connection) -> list[CouponRead]:
    rows = await db.fetch(
        """
        SELECT c.*, (
            SELECT count(*) FROM "order" o
            WHERE o.coupon_id = c.id AND o.status <> 'CANCELLED'
        ) AS uses_count
        FROM coupon c ORDER BY c.created_at DESC LIMIT 100
        """
    )
    return [CouponRead.model_validate(dict(row)) for row in rows]


async def redeem_coupon(
    db: asyncpg.Connection,
    code: str | None,
    user_id: UUID | None,
    subtotal: Decimal,
    shipping_fee: Decimal,
    *,
    lock: bool = True,
) -> tuple[UUID | None, str | None, Decimal]:
    if not code:
        return None, None, Decimal("0.00")
    normalized = normalize_code(code)
    row = await db.fetchrow(
        "SELECT * FROM coupon WHERE code = $1" + (" FOR UPDATE" if lock else ""),
        normalized,
    )
    if row is None or not row["active"]:
        raise APIException("Coupon is invalid or inactive.", status.HTTP_409_CONFLICT)
    now = await db.fetchval("SELECT NOW()")
    if (row["starts_at"] and now < row["starts_at"]) or (
        row["expires_at"] and now >= row["expires_at"]
    ):
        raise APIException(
            "Coupon is outside its valid period.", status.HTTP_409_CONFLICT
        )
    if row["assigned_user_id"] and row["assigned_user_id"] != user_id:
        raise APIException(
            "Coupon is not available for this customer.", status.HTTP_403_FORBIDDEN
        )
    if row["max_uses"] is not None:
        uses_count = await db.fetchval(
            """
            SELECT count(*) FROM "order"
            WHERE coupon_id = $1 AND status <> 'CANCELLED'
            """,
            row["id"],
        )
        if uses_count >= row["max_uses"]:
            raise APIException(
                "Coupon usage limit has been reached.", status.HTTP_409_CONFLICT
            )
    discount = (
        (subtotal * row["discount_percent"] / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if row["kind"] == "percent"
        else shipping_fee
    )
    if discount >= subtotal + shipping_fee:
        raise APIException("Coupon exceeds this order total.", status.HTTP_409_CONFLICT)
    return row["id"], normalized, discount
