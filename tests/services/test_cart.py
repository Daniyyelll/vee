import asyncio
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest

from app.core.exceptions import APIException
from app.schemas.cart import AddToCartRequest
from app.services.cart import (
    add_to_cart,
    clear_cart,
    get_cart,
    remove_cart_item,
    update_cart_item,
)


@pytest.fixture
def database_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    return value


@asynccontextmanager
async def cart_database(database_url):
    connection = await asyncpg.connect(database_url)
    schema = f"test_cart_{uuid4().hex}"
    try:
        await connection.execute(f'CREATE SCHEMA "{schema}"')
        await connection.execute(f'SET search_path TO "{schema}"')
        await connection.execute(
            """
            CREATE TABLE "user" (id UUID PRIMARY KEY);
            CREATE TABLE cart (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL UNIQUE REFERENCES "user" (id)
            );
            CREATE TABLE product (
                id UUID PRIMARY KEY,
                product_name VARCHAR NOT NULL,
                price NUMERIC(6, 2) NOT NULL,
                image_url VARCHAR,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0)
            );
            CREATE TABLE cart_item (
                id UUID PRIMARY KEY,
                cart_id UUID NOT NULL REFERENCES cart (id),
                product_id UUID NOT NULL REFERENCES product (id),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                UNIQUE (cart_id, product_id)
            );
            """
        )
        user_id, other_user_id, product_id = uuid4(), uuid4(), uuid4()
        await connection.execute(
            'INSERT INTO "user" (id) VALUES ($1), ($2)', user_id, other_user_id
        )
        await connection.execute(
            """
            INSERT INTO product (id, product_name, price, stock_quantity)
            VALUES ($1, 'T-shirt', 200.00, 10)
            """,
            product_id,
        )
        yield connection, schema, user_id, other_user_id, product_id
    finally:
        try:
            await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            await connection.close()


def test_cart_lifecycle_and_customer_isolation(database_url):
    async def scenario():
        async with cart_database(database_url) as values:
            db, _, user_id, other_user_id, product_id = values
            assert (await get_cart(db, user_id)).items == []
            cart = await add_to_cart(
                db, user_id, AddToCartRequest(product_id=product_id, quantity=2)
            )
            assert cart.total_quantity == 2
            assert cart.total_price == Decimal("400.00")

            cart = await add_to_cart(
                db, user_id, AddToCartRequest(product_id=product_id, quantity=1)
            )
            assert len(cart.items) == 1
            assert cart.items[0].quantity == 3
            cart = await update_cart_item(db, user_id, product_id, 1)
            assert cart.total_quantity == 1
            assert cart.total_price == Decimal("200.00")

            await remove_cart_item(db, other_user_id, product_id)
            await clear_cart(db, other_user_id)
            with pytest.raises(APIException) as error:
                await update_cart_item(db, other_user_id, product_id, 2)
            assert error.value.status_code == 404
            assert (await get_cart(db, user_id)).total_quantity == 1

            assert (await remove_cart_item(db, user_id, product_id)).items == []
            assert (await remove_cart_item(db, user_id, product_id)).items == []
            await add_to_cart(db, user_id, AddToCartRequest(product_id=product_id))
            cart = await clear_cart(db, user_id)
            assert cart.items == []
            assert cart.total_price == Decimal("0.00")
            assert await db.fetchval("SELECT count(*) FROM cart") == 1
            assert await db.fetchval("SELECT stock_quantity FROM product") == 10

    asyncio.run(scenario())


def test_rejected_additions_roll_back(database_url):
    async def scenario():
        async with cart_database(database_url) as values:
            db, _, user_id, _, product_id = values
            with pytest.raises(APIException) as error:
                await add_to_cart(db, user_id, AddToCartRequest(product_id=uuid4()))
            assert error.value.status_code == 404
            assert await db.fetchval("SELECT count(*) FROM cart") == 0

            await add_to_cart(
                db, user_id, AddToCartRequest(product_id=product_id, quantity=8)
            )
            with pytest.raises(APIException) as error:
                await add_to_cart(
                    db,
                    user_id,
                    AddToCartRequest(product_id=product_id, quantity=3),
                )
            assert error.value.status_code == 409
            assert (await get_cart(db, user_id)).total_quantity == 8

    asyncio.run(scenario())


def test_concurrent_additions_preserve_both_quantities(database_url):
    async def scenario():
        async with cart_database(database_url) as values:
            first, schema, user_id, _, product_id = values
            second = await asyncpg.connect(database_url)
            try:
                await second.execute(f'SET search_path TO "{schema}"')
                request = AddToCartRequest(product_id=product_id, quantity=2)
                await asyncio.gather(
                    add_to_cart(first, user_id, request),
                    add_to_cart(second, user_id, request),
                )
                cart = await get_cart(first, user_id)
                assert len(cart.items) == 1
                assert cart.total_quantity == 4
                assert cart.total_price == Decimal("800.00")
            finally:
                await second.close()

    asyncio.run(scenario())
