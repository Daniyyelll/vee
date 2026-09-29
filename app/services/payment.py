"""Cash ledger: all writes lock order, then payment, just like cancellation."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.config import settings
from app.core.exceptions import APIException
from app.domain.enums import Currency, PaymentMethod, PaymentStatus, UserRole
from app.schemas.payment import CashRefundRequest, PaymentRead

PAYMENT_COLUMNS = """
    p.id, p.order_id, o.order_number, p.amount, p.currency::text AS currency,
    p.payment_method::text AS payment_method,
    p.payment_status::text AS payment_status, p.created_at,
    p.collected_at, p.collected_by, p.refunded_at, p.refunded_by, p.refund_reason
"""


def payment_to_schema(row) -> PaymentRead:
    data = dict(row)
    data["currency"] = Currency(data["currency"])
    data["payment_method"] = PaymentMethod[data["payment_method"]]
    data["payment_status"] = PaymentStatus(data["payment_status"].lower())
    return PaymentRead.model_validate(data)


async def insert_cash_payment(db: asyncpg.Connection, order_id: UUID, amount: Decimal):
    """Called within the caller's locked order transaction; amount is server-owned."""
    await db.execute(
        """
        INSERT INTO payment (
            id, order_id, amount, currency, payment_method, payment_status
        ) VALUES ($1, $2, $3, $4, 'CASH', 'PENDING')
        ON CONFLICT (order_id) DO NOTHING
        """,
        uuid4(),
        order_id,
        amount,
        settings.payment_currency.value,
    )


async def get_payment(
    db: asyncpg.Connection, user: dict[str, Any], order_number: int
) -> PaymentRead:
    row = await db.fetchrow(
        f"""
        SELECT {PAYMENT_COLUMNS} FROM payment p
        JOIN "order" o ON o.id = p.order_id
        WHERE o.order_number = $1 AND ($2::boolean OR o.user_id = $3)
        """,
        order_number,
        user["role"] in (UserRole.ADMIN, UserRole.DELIVERY),
        user["id"],
    )
    if row is None:
        raise APIException("Payment not found.", status.HTTP_404_NOT_FOUND)
    return payment_to_schema(row)


async def _lock_order(db, order_number: int):
    row = await db.fetchrow(
        """
        SELECT id, status::text AS status, total_price FROM "order"
        WHERE order_number = $1 FOR UPDATE
        """,
        order_number,
    )
    if row is None:
        raise APIException("Order not found.", status.HTTP_404_NOT_FOUND)
    return row


def _require_collector(user):
    if user["role"] not in (UserRole.ADMIN, UserRole.DELIVERY):
        raise APIException(
            "Cash collection requires staff access.", status.HTTP_403_FORBIDDEN
        )


async def create_cash_payment(
    db: asyncpg.Connection, user: dict[str, Any], order_number: int
) -> PaymentRead:
    """Explicit staff action for orders placed before automatic cash checkout."""
    _require_collector(user)
    async with db.transaction():
        order = await _lock_order(db, order_number)
        if order["status"] == "CANCELLED":
            raise APIException(
                "Cancelled orders cannot accept cash.", status.HTTP_409_CONFLICT
            )
        if order["total_price"] is None or order["total_price"] <= 0:
            raise APIException("Order amount is invalid.", status.HTTP_409_CONFLICT)
        await insert_cash_payment(db, order["id"], order["total_price"])
        payment = await get_payment(db, user, order_number)
    return payment


async def collect_cash(
    db: asyncpg.Connection, user: dict[str, Any], order_number: int
) -> PaymentRead:
    _require_collector(user)
    async with db.transaction():
        order = await _lock_order(db, order_number)
        if order["status"] not in ("SHIPPED", "DELIVERED"):
            raise APIException(
                "Collect cash when the order is shipped or delivered.",
                status.HTTP_409_CONFLICT,
            )
        row = await db.fetchrow(
            """
            SELECT id, amount, payment_status::text AS status FROM payment
            WHERE order_id = $1 FOR UPDATE
            """,
            order["id"],
        )
        if row is None:
            raise APIException("Payment not found.", status.HTTP_404_NOT_FOUND)
        if row["amount"] != order["total_price"]:
            raise APIException(
                "Payment amount does not match the order.", status.HTTP_409_CONFLICT
            )
        if row["status"] == "COMPLETED":
            return await get_payment(db, user, order_number)
        if row["status"] != "PENDING":
            raise APIException(
                "This payment cannot be collected.", status.HTTP_409_CONFLICT
            )
        await db.execute(
            """
            UPDATE payment SET payment_status = 'COMPLETED',
                collected_at = NOW(), collected_by = $2 WHERE id = $1
            """,
            row["id"],
            user["id"],
        )
        payment = await get_payment(db, user, order_number)
    return payment


async def refund_cash(
    db: asyncpg.Connection,
    user: dict[str, Any],
    order_number: int,
    request: CashRefundRequest,
) -> PaymentRead:
    if user["role"] != UserRole.ADMIN:
        raise APIException(
            "Cash refunds require administrator access.", status.HTTP_403_FORBIDDEN
        )
    async with db.transaction():
        order = await _lock_order(db, order_number)
        row = await db.fetchrow(
            """
            SELECT id, payment_status::text AS status, refund_reason FROM payment
            WHERE order_id = $1 FOR UPDATE
            """,
            order["id"],
        )
        if row is None:
            raise APIException("Payment not found.", status.HTTP_404_NOT_FOUND)
        if row["status"] == "REFUNDED" and row["refund_reason"] == request.reason:
            return await get_payment(db, user, order_number)
        if row["status"] != "COMPLETED":
            raise APIException(
                "Only collected cash can be refunded once.", status.HTTP_409_CONFLICT
            )
        await db.execute(
            """
            UPDATE payment SET payment_status = 'REFUNDED', refunded_at = NOW(),
                refunded_by = $2, refund_reason = $3 WHERE id = $1
            """,
            row["id"],
            user["id"],
            request.reason,
        )
        payment = await get_payment(db, user, order_number)
    return payment
