from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.exceptions import APIException
from app.schemas.cart import AddToCartRequest, CartItemRead, CartRead


async def get_cart(db: asyncpg.Connection, user_id: UUID) -> CartRead:
    rows = await db.fetch(
        """
        SELECT
            ci.product_id,
            p.product_name,
            p.price AS product_price,
            p.image_url AS product_image,
            ci.quantity,
            p.price * ci.quantity AS subtotal
        FROM cart as c
        JOIN cart_item AS ci ON ci.cart_id = c.id
        JOIN product AS p ON p.id = ci.product_id
        WHERE c.user_id = $1
        ORDER BY ci.id
        """,
        user_id,
    )

    items = [CartItemRead.model_validate(dict(row)) for row in rows]

    return CartRead(
        user_id=user_id,
        items=items,
        total_quantity=sum(item.quantity for item in items),
        total_price=sum((item.subtotal for item in items), Decimal("0.00")),
    )


async def _lock_cart(
    db: asyncpg.Connection,
    user_id: UUID,
    *,
    create: bool,
) -> UUID | None:
    if create:
        await db.execute(
            """
            INSERT INTO cart (id, user_id) VALUES ($1, $2)
                ON CONFLICT (user_id) DO NOTHING
            """,
            uuid4(),
            user_id,
        )

    return await db.fetchval(
        """
        SELECT id FROM cart WHERE user_id = $1
        FOR UPDATE""",
        user_id,
    )


async def _change_quantity(
    db: asyncpg.Connection,
    user_id: UUID,
    product_id: UUID,
    quantity: int,
    *,
    increase: bool,
) -> CartRead:
    if quantity <= 0:
        raise APIException(
            message="Quantity must be greater than zero",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    async with db.transaction():
        cart_id = await _lock_cart(db, user_id, create=increase)

        if cart_id is None:
            raise APIException(
                message="Cart item not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        existing_quantity = await db.fetchval(
            """
            SELECT quantity
            FROM cart_item
            WHERE cart_id = $1 AND product_id = $2""",
            cart_id,
            product_id,
        )

        if not increase and existing_quantity is None:
            raise APIException(
                message="Cart item not found",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        product = await db.fetchrow(
            """
            SELECT stock_quantity
            FROM product
            WHERE id = $1
            FOR SHARE""",
            product_id,
        )

        if product is None:
            raise APIException(
                message="Product not found.",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        if increase:
            new_quantity = (existing_quantity or 0) + quantity
        else:
            new_quantity = quantity

        if new_quantity > product["stock_quantity"]:
            raise APIException(
                message="Requested quantity exceeds available stock.",
                status_code=status.HTTP_409_CONFLICT,
            )

        await db.execute(
            """
            INSERT INTO cart_item (
            id, cart_id, product_id, quantity)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (cart_id, product_id)
                DO UPDATE SET quantity = EXCLUDED.quantity
            """,
            uuid4(),
            cart_id,
            product_id,
            new_quantity,
        )

        cart = await get_cart(db, user_id)

    return cart


async def add_to_cart(
    db: asyncpg.Connection,
    user_id: UUID,
    request: AddToCartRequest,
) -> CartRead:
    return await _change_quantity(
        db,
        user_id,
        request.product_id,
        request.quantity,
        increase=True,
    )


async def update_cart_item(
    db: asyncpg.Connection,
    user_id: UUID,
    product_id: UUID,
    quantity: int,
) -> CartRead:
    return await _change_quantity(
        db,
        user_id,
        product_id,
        quantity,
        increase=False,
    )


async def remove_cart_item(
    db: asyncpg.Connection, user_id: UUID, product_id: UUID
) -> CartRead:
    async with db.transaction():
        cart_id = await _lock_cart(db, user_id, create=False)

        if cart_id is not None:
            await db.execute(
                """
                DELETE FROM cart_item
                WHERE cart_id = $1
                AND product_id = $2""",
                cart_id,
                product_id,
            )

        cart = await get_cart(db, user_id)

    return cart


async def clear_cart(
    db: asyncpg.Connection,
    user_id: UUID,
) -> CartRead:
    async with db.transaction():
        cart_id = await _lock_cart(db, user_id, create=False)

        if cart_id is not None:
            await db.execute(
                """
                DELETE FROM cart_item
                WHERE cart_id = $1""",
                cart_id,
            )

        cart = await get_cart(db, user_id)

    return cart
