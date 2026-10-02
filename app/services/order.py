"""Order checkout, ownership and inventory lifecycle."""

import hmac
import json
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.config import settings
from app.core.exceptions import APIException
from app.domain.enums import DeliveryArea, OrderStatus, UserRole
from app.schemas.order import (
    CheckoutRequest,
    GuestCheckoutItem,
    GuestCheckoutRequest,
    OrderQuote,
    OrderRead,
    OrderReceiptRead,
    QuoteItemRead,
)
from app.services.cart import _lock_cart
from app.services.coupon import redeem_coupon
from app.services.outbox import enqueue_email
from app.services.payment import (
    PAYMENT_COLUMNS,
    insert_cash_payment,
    payment_to_schema,
)
from app.services.user import user_to_dict

ORDER_COLUMNS = """
    o.id, o.order_number, o.total_price, o.status::text AS status,
    o.shipping_address, o.delivery_area, o.created_at, o.guest_name, o.guest_email,
    o.guest_phone, o.recipient_name, o.recipient_phone,
    o.subtotal_price, o.discount_amount, o.shipping_fee,
    o.coupon_code, o.currency::text AS currency, o.expires_at,
    u.id AS user_id, u.name, u.email, u.role::text AS role, u.active,
    u.address, u.phone
"""

TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


def order_receipt_token(order_id: UUID) -> str:
    """A receipt capability separate from sequential order numbers and JWTs."""
    secret = settings.checkout_hmac_key or settings.secret_jwt_key
    return hmac.new(
        secret.encode(), f"vee-order-receipt:{order_id}".encode(), sha256
    ).hexdigest()


async def get_order_receipt(
    db: asyncpg.Connection, order_number: int, receipt_token: str
) -> OrderReceiptRead:
    row = await db.fetchrow(
        """
        SELECT id, order_number, total_price, currency::text AS currency,
               recipient_name, recipient_phone, shipping_address, delivery_area
        FROM "order"
        WHERE order_number = $1 AND created_at > NOW() - INTERVAL '30 days'
        """,
        order_number,
    )
    if row is None or not hmac.compare_digest(
        order_receipt_token(row["id"]), receipt_token
    ):
        raise APIException("Order receipt not found.", status.HTTP_404_NOT_FOUND)
    return OrderReceiptRead.model_validate(dict(row))


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
    payments = await db.fetch(
        f"""
        SELECT {PAYMENT_COLUMNS} FROM payment p
        JOIN "order" o ON o.id = p.order_id
        WHERE p.order_id = ANY($1::uuid[])
        """,
        [row["id"] for row in rows],
    )
    payments_by_order = {
        payment["order_id"]: payment_to_schema(payment) for payment in payments
    }
    grouped = {}
    for item in items:
        grouped.setdefault(item["order_id"], []).append(dict(item))
    orders = []
    for row in rows:
        data = dict(row)
        data["status"] = OrderStatus(data["status"].lower())
        data["user"] = (
            user_to_dict({**data, "id": data["user_id"]})
            if data["user_id"] is not None
            else None
        )
        data["items"] = grouped.get(data["id"], [])
        data["payment"] = payments_by_order.get(data["id"])
        orders.append(OrderRead.model_validate(data))
    return orders


async def get_order(
    db: asyncpg.Connection, user: dict[str, Any], order_number: int
) -> OrderRead:
    row = await db.fetchrow(
        f"""
        SELECT {ORDER_COLUMNS}
        FROM "order" o LEFT JOIN "user" u ON u.id = o.user_id
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
        FROM "order" o LEFT JOIN "user" u ON u.id = o.user_id
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
                   p.stock_quantity, p.active, p.currency::text AS currency,
                   ci.quantity
            FROM cart_item ci JOIN product p ON p.id = ci.product_id
            WHERE ci.cart_id = $1 ORDER BY p.id FOR UPDATE OF p
            """,
            cart_id,
        )
        if not items:
            raise APIException("Your cart is empty.")
        result = await _create_order(
            db,
            items,
            request.shipping_address,
            request.coupon_code,
            user_id=user["id"],
            recipient_name=request.name,
            recipient_phone=request.phone,
            delivery_area=request.delivery_area,
            expected_total=request.expected_total,
        )
        await db.execute("DELETE FROM cart_item WHERE cart_id = $1", cart_id)
    return result


async def guest_checkout(
    db: asyncpg.Connection, request: GuestCheckoutRequest, idempotency_key: str
) -> OrderRead:
    key = hmac.new(
        (settings.checkout_hmac_key or settings.secret_jwt_key).encode(),
        idempotency_key.encode(),
        sha256,
    ).hexdigest()
    request_hash = sha256(
        json.dumps(request.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    quantities = _requested_quantities(request.items)
    async with db.transaction():
        await db.execute(
            """
            INSERT INTO guest_checkout_request (key, request_hash)
            VALUES ($1, $2) ON CONFLICT (key) DO NOTHING
            """,
            key,
            request_hash,
        )
        attempt = await db.fetchrow(
            "SELECT request_hash, order_id FROM guest_checkout_request "
            "WHERE key = $1 FOR UPDATE",
            key,
        )
        if attempt["request_hash"] != request_hash:
            raise APIException(
                "Idempotency key was used for another request.",
                status.HTTP_409_CONFLICT,
            )
        if attempt["order_id"]:
            row = await db.fetchrow(
                f"""SELECT {ORDER_COLUMNS} FROM "order" o
                LEFT JOIN "user" u ON u.id = o.user_id WHERE o.id = $1""",
                attempt["order_id"],
            )
            return (await _read_orders(db, [row]))[0]
        products = await db.fetch(
            """
            SELECT id AS product_id, product_name, price, stock_quantity,
                   active, currency::text AS currency
            FROM product WHERE id = ANY($1::uuid[])
            ORDER BY id FOR UPDATE
            """,
            list(quantities),
        )
        if len(products) != len(quantities):
            raise APIException("Product not found.", status.HTTP_404_NOT_FOUND)
        items = [
            {**dict(row), "quantity": quantities[row["product_id"]]} for row in products
        ]
        order = await _create_order(
            db,
            items,
            request.shipping_address,
            request.coupon_code,
            guest_name=request.name,
            guest_email=str(request.email),
            guest_phone=request.phone,
            recipient_name=request.name,
            recipient_phone=request.phone,
            delivery_area=request.delivery_area,
            expected_total=request.expected_total,
        )
        await db.execute(
            "UPDATE guest_checkout_request SET order_id = $2 WHERE key = $1",
            key,
            order.id,
        )
        return order


def _requested_quantities(items: list[GuestCheckoutItem]) -> dict[UUID, int]:
    quantities = {}
    for item in items:
        if item.product_id in quantities:
            raise APIException("Each product may appear only once.")
        quantities[item.product_id] = item.quantity
    return quantities


async def quote_guest_order(
    db: asyncpg.Connection,
    items: list[GuestCheckoutItem],
    coupon_code: str | None,
) -> OrderQuote:
    quantities = _requested_quantities(items)
    products = await db.fetch(
        """
        SELECT id AS product_id, product_name, price, stock_quantity,
               active, currency::text AS currency
        FROM product WHERE id = ANY($1::uuid[])
        ORDER BY id
        """,
        list(quantities),
    )
    if len(products) != len(quantities):
        raise APIException("Product not found.", status.HTTP_404_NOT_FOUND)
    rows = [
        {**dict(row), "quantity": quantities[row["product_id"]]} for row in products
    ]
    quote, _ = await _price_items(db, rows, coupon_code, None, lock_coupon=False)
    return quote


async def quote_cart_order(
    db: asyncpg.Connection, user_id: UUID, coupon_code: str | None
) -> OrderQuote:
    rows = await db.fetch(
        """
        SELECT p.id AS product_id, p.product_name, p.price,
               p.stock_quantity, p.active, p.currency::text AS currency,
               ci.quantity
        FROM cart c JOIN cart_item ci ON ci.cart_id = c.id
        JOIN product p ON p.id = ci.product_id
        WHERE c.user_id = $1 ORDER BY p.id
        """,
        user_id,
    )
    if not rows:
        raise APIException("Your cart is empty.")
    quote, _ = await _price_items(db, rows, coupon_code, user_id, lock_coupon=False)
    return quote


async def _price_items(
    db: asyncpg.Connection,
    items,
    coupon_code: str | None,
    user_id: UUID | None,
    *,
    lock_coupon: bool,
) -> tuple[OrderQuote, UUID | None]:
    if not items:
        raise APIException("Your cart is empty.")
    quoted_items = []
    for item in items:
        if not item["active"]:
            raise APIException("Product is unavailable.", status.HTTP_409_CONFLICT)
        if item["currency"] != settings.payment_currency.value:
            raise APIException(
                "Product currency does not match the store.",
                status.HTTP_409_CONFLICT,
            )
        if item["quantity"] > item["stock_quantity"]:
            raise APIException(
                f"Insufficient stock for {item['product_name']}.",
                status.HTTP_409_CONFLICT,
            )
        if item["price"] is None or item["price"] <= 0:
            raise APIException("Product price unavailable.", status.HTTP_409_CONFLICT)
        quoted_items.append(
            QuoteItemRead(
                product_id=item["product_id"],
                product_name=item["product_name"],
                quantity=item["quantity"],
                unit_price=item["price"],
                subtotal=item["price"] * item["quantity"],
            )
        )
    subtotal = sum((item.subtotal for item in quoted_items), Decimal("0.00"))
    coupon_id, applied_code, discount = await redeem_coupon(
        db, coupon_code, user_id, subtotal, settings.shipping_fee, lock=lock_coupon
    )
    total = subtotal + settings.shipping_fee - discount
    if total > Decimal("99999999.99"):
        raise APIException("Order total exceeds the supported limit.")
    return (
        OrderQuote(
            items=quoted_items,
            subtotal_price=subtotal,
            shipping_fee=settings.shipping_fee,
            discount_amount=discount,
            total_price=total,
            coupon_code=applied_code,
            currency=settings.payment_currency,
        ),
        coupon_id,
    )


async def _create_order(
    db: asyncpg.Connection,
    items,
    shipping_address: str,
    coupon_code: str | None,
    *,
    user_id: UUID | None = None,
    guest_name: str | None = None,
    guest_email: str | None = None,
    guest_phone: str | None = None,
    recipient_name: str,
    recipient_phone: str,
    delivery_area: DeliveryArea,
    expected_total: Decimal | None = None,
) -> OrderRead:
    quote, coupon_id = await _price_items(
        db, items, coupon_code, user_id, lock_coupon=True
    )
    if expected_total is not None and quote.total_price != expected_total:
        raise APIException(
            "Your order total changed. Please review the updated total and try again.",
            status.HTTP_409_CONFLICT,
        )
    order_id = uuid4()
    await db.execute(
        """
            INSERT INTO "order" (
                id, order_number, total_price, subtotal_price, discount_amount,
                shipping_fee,
                coupon_id, coupon_code, shipping_address, delivery_area,
                status, user_id,
                guest_name, guest_email, guest_phone, recipient_name,
                recipient_phone, currency, expires_at
            ) VALUES ($1, nextval('order_number_seq'), $2, $3, $4, $5,
                      $6, $7, $8, $9, 'PENDING', $10, $11, $12, $13,
                      $14, $15, $16, NOW() + INTERVAL '24 hours')
            """,
        order_id,
        quote.total_price,
        quote.subtotal_price,
        quote.discount_amount,
        quote.shipping_fee,
        coupon_id,
        quote.coupon_code,
        shipping_address,
        delivery_area.value,
        user_id,
        guest_name,
        guest_email,
        guest_phone,
        recipient_name,
        recipient_phone,
        quote.currency.value,
    )
    await db.executemany(
        """
            INSERT INTO order_item (
                id, order_id, product_id, product_name, quantity, unit_price,
                is_reviewed
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::uuid IS NOT NULL AND EXISTS (
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
                user_id,
            )
            for item in items
        ],
    )
    await db.executemany(
        "UPDATE product SET stock_quantity = stock_quantity - $2 WHERE id = $1",
        [(item["product_id"], item["quantity"]) for item in items],
    )
    await insert_cash_payment(db, order_id, quote.total_price)
    await enqueue_email(db, "order_confirmation", {"order_id": str(order_id)})
    row = await db.fetchrow(
        f"""SELECT {ORDER_COLUMNS} FROM "order" o
            LEFT JOIN "user" u ON u.id = o.user_id WHERE o.id = $1""",
        order_id,
    )
    return (await _read_orders(db, [row]))[0]


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
        if new_status == OrderStatus.DELIVERED:
            payment_status = await db.fetchval(
                "SELECT payment_status::text FROM payment WHERE order_id = $1",
                row["id"],
            )
            if payment_status != "COMPLETED":
                raise APIException(
                    "Record cash collection before delivery.", status.HTTP_409_CONFLICT
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
        await enqueue_email(
            db, "order_status", {"order_id": str(row["id"]), "status": new_status.value}
        )
        result = await get_order(db, user, order_number)
    return result


async def expire_pending_orders(db: asyncpg.Connection) -> int:
    """Release stale COD reservations using the normal cancellation workflow."""
    rows = await db.fetch(
        """
        SELECT order_number FROM "order"
        WHERE status = 'PENDING' AND expires_at <= NOW()
        ORDER BY expires_at LIMIT 100
        """
    )
    staff = {"id": UUID(int=0), "role": UserRole.ADMIN}
    expired = 0
    for row in rows:
        try:
            await update_order_status(
                db, staff, row["order_number"], OrderStatus.CANCELLED
            )
        except APIException as exc:
            if exc.status_code != status.HTTP_409_CONFLICT:
                raise
        else:
            expired += 1
    return expired
