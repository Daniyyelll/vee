"""Real PostgreSQL cash ledger, order gates and audit behavior."""

import asyncio
import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import asyncpg
import pytest

from app.core.exceptions import APIException
from app.domain.enums import OrderStatus, PaymentMethod, PaymentStatus, UserRole
from app.schemas.order import CheckoutRequest
from app.schemas.payment import CashRefundRequest
from app.services import payment as payment_service
from app.services.order import assign_order_delivery, update_order_status
from app.services.payment import (
    collect_cash,
    create_cash_payment,
    get_payment,
    refund_cash,
)
from tests.services.test_commerce import (
    buy,
    commerce_database,
    database_url as database_url,
)


async def ship(db, admin, order):
    await update_order_status(db, admin, order.order_number, OrderStatus.PROCESSING)
    await update_order_status(db, admin, order.order_number, OrderStatus.SHIPPED)


def test_cash_checkout_collection_delivery_and_refund(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, _, admin, delivery = users
            order = await buy(db, customer, product_id)
            await assign_order_delivery(db, admin, order.order_number, delivery["id"])
            payment = order.payment
            assert payment.amount == Decimal("450.00")
            assert payment.payment_status == PaymentStatus.PENDING
            assert payment.payment_method == PaymentMethod.CASH
            assert payment.collected_at is None and payment.collected_by is None
            assert (
                await db.fetchval("SELECT provider_transaction_id FROM payment") is None
            )
            await ship(db, admin, order)
            with pytest.raises(APIException) as error:
                await update_order_status(
                    db, delivery, order.order_number, OrderStatus.DELIVERED
                )
            assert error.value.status_code == 409
            collected = await collect_cash(db, delivery, order.order_number)
            assert collected.payment_status == PaymentStatus.COMPLETED
            assert collected.collected_by == delivery["id"]
            assert collected.collected_at is not None
            repeated = await collect_cash(db, admin, order.order_number)
            assert repeated == collected
            delivered = await update_order_status(
                db, delivery, order.order_number, OrderStatus.DELIVERED
            )
            assert delivered.payment.payment_status == PaymentStatus.COMPLETED
            request = CashRefundRequest(reason="Returned item; cash handed back")
            refunded = await refund_cash(db, admin, order.order_number, request)
            assert refunded.payment_status == PaymentStatus.REFUNDED
            assert refunded.refunded_by == admin["id"]
            assert refunded.refunded_at is not None
            assert refunded.collected_by == delivery["id"]
            assert refunded.refund_reason == request.reason
            assert await refund_cash(db, admin, order.order_number, request) == refunded
            with pytest.raises(APIException) as error:
                await refund_cash(
                    db,
                    admin,
                    order.order_number,
                    CashRefundRequest(reason="Another reason"),
                )
            assert error.value.status_code == 409
            with pytest.raises(APIException) as error:
                await collect_cash(db, admin, order.order_number)
            assert error.value.status_code == 409
            assert await db.fetchval("SELECT stock_quantity FROM product") == 10

    asyncio.run(scenario())


def test_cash_ownership_permissions_and_invalid_states(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, other, admin, delivery = users
            order = await buy(db, customer, product_id)
            with pytest.raises(APIException) as error:
                await get_payment(db, delivery, order.order_number)
            assert error.value.status_code == 404
            with pytest.raises(APIException) as error:
                await collect_cash(db, delivery, order.order_number)
            assert error.value.status_code == 404
            await assign_order_delivery(db, admin, order.order_number, delivery["id"])
            assert (
                await get_payment(db, customer, order.order_number)
            ).id == order.payment.id
            with pytest.raises(APIException) as error:
                await get_payment(db, other, order.order_number)
            assert error.value.status_code == 404
            for service in (collect_cash, create_cash_payment):
                with pytest.raises(APIException) as error:
                    await service(db, customer, order.order_number)
                assert error.value.status_code == 403
            with pytest.raises(APIException) as error:
                await collect_cash(db, admin, order.order_number)
            assert error.value.status_code == 409
            request = CashRefundRequest(reason="Return")
            with pytest.raises(APIException) as error:
                await refund_cash(db, delivery, order.order_number, request)
            assert error.value.status_code == 403
            with pytest.raises(APIException) as error:
                await refund_cash(db, admin, order.order_number, request)
            assert error.value.status_code == 409
            await update_order_status(
                db, customer, order.order_number, OrderStatus.CANCELLED
            )
            payment = await get_payment(db, customer, order.order_number)
            assert payment.payment_status == PaymentStatus.CANCELLED
            for service in (collect_cash, create_cash_payment):
                with pytest.raises(APIException) as error:
                    await service(db, admin, order.order_number)
                assert error.value.status_code == 409
            assert await db.fetchval("SELECT count(*) FROM payment") == 1

    asyncio.run(scenario())


def test_legacy_payment_creation_uses_order_total_and_preserves_status(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, _, admin, _ = users
            order = await buy(db, customer, product_id)
            await db.execute("DELETE FROM payment WHERE order_id = $1", order.id)
            with pytest.raises(APIException) as error:
                await get_payment(db, customer, order.order_number)
            assert error.value.status_code == 404
            payment = await create_cash_payment(db, admin, order.order_number)
            assert payment.amount == order.total_price
            assert await create_cash_payment(db, admin, order.order_number) == payment
            await ship(db, admin, order)
            await db.execute(
                "UPDATE payment SET amount = 1 WHERE order_id = $1", order.id
            )
            with pytest.raises(APIException) as error:
                await collect_cash(db, admin, order.order_number)
            assert error.value.status_code == 409
            assert (
                await get_payment(db, admin, order.order_number)
            ).collected_at is None

    asyncio.run(scenario())


def test_concurrent_collectors_preserve_one_collection_audit(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, schema, users, product_id):
            customer, _, admin, delivery = users
            order = await buy(db, customer, product_id)
            await assign_order_delivery(db, admin, order.order_number, delivery["id"])
            await ship(db, admin, order)
            second = await asyncpg.connect(database_url)
            try:
                await second.execute(f'SET search_path TO "{schema}"')
                first_result, second_result = await asyncio.wait_for(
                    asyncio.gather(
                        collect_cash(db, admin, order.order_number),
                        collect_cash(second, delivery, order.order_number),
                    ),
                    timeout=10,
                )
                assert first_result == second_result
                assert first_result.collected_by in (admin["id"], delivery["id"])
                assert await db.fetchval("SELECT count(*) FROM payment") == 1
            finally:
                await second.close()

    asyncio.run(scenario())


def test_payment_insert_failure_rolls_back_order_cart_and_stock(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            from app.schemas.cart import AddToCartRequest
            from app.services.cart import add_to_cart, get_cart
            from app.services.order import checkout

            customer = users[0]
            await add_to_cart(
                db, customer["id"], AddToCartRequest(product_id=product_id, quantity=2)
            )
            await db.execute(
                "ALTER TABLE payment ADD CONSTRAINT test_failure CHECK (amount < 1)"
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await checkout(
                    db,
                    customer,
                    CheckoutRequest(
                        name="Buyer",
                        phone="01012345678",
                        shipping_address="Cairo",
                        delivery_area="Cairo",
                    ),
                )
            assert await db.fetchval('SELECT count(*) FROM "order"') == 0
            assert await db.fetchval("SELECT count(*) FROM payment") == 0
            assert await db.fetchval("SELECT stock_quantity FROM product") == 10
            assert (await get_cart(db, customer["id"])).total_quantity == 2

    asyncio.run(scenario())


def test_cash_migration_preserves_records_on_downgrade_and_upgrade(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            order = await buy(db, users[0], product_id)
            path = Path("migrations/versions/c6f13a4d9e52_cash_payments.py")
            spec = importlib.util.spec_from_file_location("cash_migration", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for direction in (module.downgrade, module.upgrade):
                statements = []
                module.op = SimpleNamespace(execute=statements.append)
                direction()
                for statement in statements:
                    await db.execute(statement)
            assert (
                await get_payment(db, users[0], order.order_number)
            ).id == order.payment.id
            with pytest.raises(asyncpg.UniqueViolationError):
                await db.execute(
                    """INSERT INTO payment (id, amount, currency, payment_status,
                    payment_method, order_id)
                    VALUES ($1, 400, 'EGP', 'PENDING', 'CASH', $2)""",
                    uuid4(),
                    order.id,
                )
            with pytest.raises(asyncpg.CheckViolationError):
                await db.execute("UPDATE payment SET payment_method = 'INSTAPAY'")

    asyncio.run(scenario())


def test_refund_restocks_once_inside_payment_transaction(monkeypatch):
    product_id, order_id, payment_id, admin_id = (uuid4() for _ in range(4))
    db = MagicMock()
    db.fetchrow = AsyncMock(
        side_effect=[
            {"id": payment_id, "status": "COMPLETED", "refund_reason": None},
            {"id": payment_id, "status": "REFUNDED", "refund_reason": "Returned"},
        ]
    )
    db.fetch = AsyncMock(return_value=[{"id": product_id, "quantity": 2}])
    db.executemany = AsyncMock()
    db.execute = AsyncMock()
    monkeypatch.setattr(
        payment_service,
        "_lock_order",
        AsyncMock(return_value={"id": order_id, "status": "DELIVERED"}),
    )
    result = object()
    monkeypatch.setattr(payment_service, "get_payment", AsyncMock(return_value=result))
    admin = {"id": admin_id, "role": UserRole.ADMIN}
    request = CashRefundRequest(reason="Returned")

    assert asyncio.run(refund_cash(db, admin, 42, request)) is result
    assert asyncio.run(refund_cash(db, admin, 42, request)) is result
    db.executemany.assert_awaited_once()
    assert db.executemany.await_args.args[1] == [(product_id, 2)]
    assert "FOR UPDATE OF p" in db.fetch.await_args.args[0]
    assert db.execute.await_count == 2
    assert "UPDATE payment" in db.execute.await_args_list[0].args[0]
    assert "INSERT INTO audit_event" in db.execute.await_args_list[1].args[0]
