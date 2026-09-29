"""Order checkout, ownership and inventory lifecycle."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.domain.enums import OrderStatus, UserRole
from app.schemas.order import CheckoutRequest, OrderRead
from app.services.cart import _lock_cart
from app.services.user import user_to_dict

ORDER_COLUMNS = """
    o.id, o.order_number, o.total_price, o.status::text AS status,
    o.shipping_address, o.created_at,
    u.id AS user_id, u.name, u.email, u.role::text AS role, u.active, u.address
"""

TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


async def _read_orders(db: asyncpg.Connection, rows) -> list[OrderRead]:
    if not rows:
        return []
    items = await db.fetch(
        """
        SELECT id, order_id, product_id, product_name, quantity, unit_price,
               is_reviewed
        FROM order_item WHERE order_id = ANY($1::uuid[])
        ORDER BY order_id, id
        """,
        [row["id"] for row in rows],
    )
    grouped = {}
    for item in items:
        grouped.setdefault(item["order_id"], []).append(dict(item))
    orders = []
    for row in rows:
        data = dict(row)
        data["status"] = OrderStatus(data["status"].lower())
        data["user"] = user_to_dict({**data, "id": data["user_id"]})
        data["items"] = grouped.get(data["id"], [])
        orders.append(OrderRead.model_validate(data))
    return orders


async def get_order(
    db: asyncpg.Connection, user: dict[str, Any], order_number: int
) -> OrderRead:
    row = await db.fetchrow(
        f"""
        SELECT {ORDER_COLUMNS}
        FROM "order" o JOIN "user" u ON u.id = o.user_id
        WHERE o.order_number = $1 AND ($2::boolean OR o.user_id = $3)
        """,
        order_number,
        user["role"] in (UserRole.ADMIN, UserRole.DELIVERY),
        user["id"],
    )
    if row is None:
        raise APIException("Order not found.", status.HTTP_404_NOT_FOUND)
    return (await _read_orders(db, [row]))[0]


async def list_orders(
    db: asyncpg.Connection,
    user: dict[str, Any],
    order_status: OrderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[OrderRead]:
    rows = await db.fetch(
        f"""
        SELECT {ORDER_COLUMNS}
        FROM "order" o JOIN "user" u ON u.id = o.user_id
        WHERE ($1::boolean OR o.user_id = $2)
          AND ($3::text IS NULL OR o.status::text = $3)
        ORDER BY o.created_at DESC, o.order_number DESC LIMIT $4 OFFSET $5
        """,
        user["role"] in (UserRole.ADMIN, UserRole.DELIVERY),
        user["id"],
        order_status.name if order_status else None,
        limit,
        offset,
    )
    return await _read_orders(db, rows)


async def checkout(
    db: asyncpg.Connection, user: dict[str, Any], request: CheckoutRequest
) -> OrderRead:
    async with db.transaction():
        await db.execute('SELECT id FROM "user" WHERE id = $1 FOR UPDATE', user["id"])
        cart_id = await _lock_cart(db, user["id"], create=False)
        if cart_id is None:
            raise APIException("Your cart is empty.")
        # Cart mutations use the same cart lock; stock locks are ordered to
        # avoid deadlocks when different customers buy overlapping products.
        items = await db.fetch(
            """
            SELECT p.id AS product_id, p.product_name, p.price,
                   p.stock_quantity, ci.quantity
            FROM cart_item ci JOIN product p ON p.id = ci.product_id
            WHERE ci.cart_id = $1 ORDER BY p.id FOR UPDATE OF p
            """,
            cart_id,
        )
        if not items:
            raise APIException("Your cart is empty.")
        for item in items:
            if item["quantity"] > item["stock_quantity"]:
                raise APIException(
                    f"Insufficient stock for {item['product_name']}.",
                    status.HTTP_409_CONFLICT,
                )
            if item["price"] is None or item["price"] <= 0:
                raise APIException(
                    "Product price unavailable.", status.HTTP_409_CONFLICT
                )
        total = sum(
            (item["price"] * item["quantity"] for item in items), Decimal("0.00")
        )
        if total > Decimal("99999999.99"):
            raise APIException("Order total exceeds the supported limit.")
        order_id = uuid4()
        number = await db.fetchval(
            """
            INSERT INTO "order" (
                id, order_number, total_price, shipping_address, status, user_id
            ) VALUES ($1, nextval('order_number_seq'), $2, $3, 'PENDING', $4)
            RETURNING order_number
            """,
            order_id,
            total,
            request.shipping_address,
            user["id"],
        )
        await db.executemany(
            """
            INSERT INTO order_item (
                id, order_id, product_id, product_name, quantity, unit_price,
                is_reviewed
            ) VALUES ($1, $2, $3, $4, $5, $6, EXISTS (
                SELECT 1 FROM review WHERE user_id = $7 AND product_id = $3
            ))
            """,
            [
                (
                    uuid4(),
                    order_id,
                    item["product_id"],
                    item["product_name"],
                    item["quantity"],
                    item["price"],
                    user["id"],
                )
                for item in items
            ],
        )
        await db.executemany(
            "UPDATE product SET stock_quantity = stock_quantity - $2 WHERE id = $1",
            [(item["product_id"], item["quantity"]) for item in items],
        )
        await db.execute("DELETE FROM cart_item WHERE cart_id = $1", cart_id)
        result = await get_order(db, user, number)
    return result


async def update_order_status(
    db: asyncpg.Connection,
    user: dict[str, Any],
    order_number: int,
    new_status: OrderStatus,
) -> OrderRead:
    async with db.transaction():
        row = await db.fetchrow(
            """
            SELECT id, user_id, status::text AS status FROM "order"
            WHERE order_number = $1 FOR UPDATE
            """,
            order_number,
        )
        if row is None or (
            user["role"] == UserRole.CUSTOMER and row["user_id"] != user["id"]
        ):
            raise APIException("Order not found.", status.HTTP_404_NOT_FOUND)
        current = OrderStatus(row["status"].lower())
        if user["role"] == UserRole.CUSTOMER and (
            new_status != OrderStatus.CANCELLED
            or current not in (OrderStatus.PENDING, OrderStatus.CANCELLED)
        ):
            raise APIException(
                "Customers can only cancel pending orders.", status.HTTP_403_FORBIDDEN
            )
        if user["role"] == UserRole.DELIVERY and (
            new_status not in (OrderStatus.SHIPPED, OrderStatus.DELIVERED)
            or (
                current != new_status
                and current not in (OrderStatus.PROCESSING, OrderStatus.SHIPPED)
            )
        ):
            raise APIException(
                "Delivery staff can only ship or deliver orders.",
                status.HTTP_403_FORBIDDEN,
            )
        if current == new_status:
            return await get_order(db, user, order_number)
        if new_status not in TRANSITIONS[current]:
            raise APIException(
                "Invalid order status transition.", status.HTTP_409_CONFLICT
            )
        if new_status == OrderStatus.CANCELLED:
            # Payment/refund processing is a separate workflow. Do not cancel
            # an order with a settled payment without a refund integration.
            payments = await db.fetch(
                """
                SELECT payment_status::text AS status FROM payment
                WHERE order_id = $1 FOR UPDATE
                """,
                row["id"],
            )
            if any(payment["status"] == "COMPLETED" for payment in payments):
                raise APIException(
                    "Paid orders require a refund before cancellation.",
                    status.HTTP_409_CONFLICT,
                )
            items = await db.fetch(
                """
                SELECT p.id, oi.quantity FROM order_item oi
                JOIN product p ON p.id = oi.product_id
                WHERE oi.order_id = $1 ORDER BY p.id FOR UPDATE OF p
                """,
                row["id"],
            )
            await db.executemany(
                "UPDATE product SET stock_quantity = stock_quantity + $2 WHERE id = $1",
                [(item["id"], item["quantity"]) for item in items],
            )
            await db.execute(
                """
                UPDATE payment SET payment_status = 'CANCELLED'
                WHERE order_id = $1 AND payment_status = 'PENDING'
                """,
                row["id"],
            )
        await db.execute(
            'UPDATE "order" SET status = $2 WHERE id = $1', row["id"], new_status.name
        )
        result = await get_order(db, user, order_number)
    return result
