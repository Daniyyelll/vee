"""Exercise real SQL in isolated schemas; never modify application tables."""

import asyncio
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest

from app.core.exceptions import APIException
from app.domain.enums import OrderStatus, ReportStatus, UserRole
from app.schemas.cart import AddToCartRequest
from app.schemas.order import CheckoutRequest
from app.schemas.report import ReportCreate, ReportUpdate, SalesPeriod
from app.schemas.review import ReviewCreate, ReviewUpdate
from app.services.cart import add_to_cart, get_cart
from app.services.order import checkout, get_order, list_orders, update_order_status
from app.services.payment import collect_cash
from app.services.report import (
    create_report,
    get_report,
    list_reports,
    sales_report,
    update_report,
)
from app.services.review import (
    create_review,
    delete_review,
    list_reviews,
    update_review,
)


@pytest.fixture
def database_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    return value


def migration_statements():
    modules = {}
    for path in Path("migrations/versions").glob("*.py"):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[module.down_revision] = module
    statements = []
    revision = None
    while revision in modules:
        module = modules[revision]
        module.op = SimpleNamespace(execute=statements.append)
        module.upgrade()
        revision = module.revision
    return [statement for statement in statements if statement.strip()]


@asynccontextmanager
async def commerce_database(database_url):
    db = await asyncpg.connect(database_url)
    schema = f"test_commerce_{uuid4().hex}"
    try:
        await db.execute(f'CREATE SCHEMA "{schema}"')
        await db.execute(f'SET search_path TO "{schema}"')
        for statement in migration_statements():
            await db.execute(statement)
        users = []
        for index, role in enumerate(
            (UserRole.CUSTOMER, UserRole.CUSTOMER, UserRole.ADMIN, UserRole.DELIVERY)
        ):
            user = {
                "id": uuid4(),
                "name": f"User{index}",
                "email": f"user{index}@example.com",
                "role": role,
            }
            await db.execute(
                """INSERT INTO "user" (id, name, email, hashed_password, role, active)
                VALUES ($1, $2, $3, 'unused', $4, TRUE)""",
                user["id"],
                user["name"],
                user["email"],
                role.name,
            )
            users.append(user)
        category_id, product_id = uuid4(), uuid4()
        await db.execute(
            "INSERT INTO category (id, category_name) VALUES ($1, 'Clothes')",
            category_id,
        )
        await db.execute(
            """INSERT INTO product (
            id, product_name, price, stock_quantity, category_id, product_slug)
            VALUES ($1, 'T-shirt', 200.00, 10, $2, 't-shirt')""",
            product_id,
            category_id,
        )
        yield db, schema, users, product_id
    finally:
        try:
            await db.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            await db.close()


async def buy(db, user, product_id, quantity=2):
    await add_to_cart(
        db, user["id"], AddToCartRequest(product_id=product_id, quantity=quantity)
    )
    return await checkout(db, user, CheckoutRequest(shipping_address="Cairo"))


async def deliver(db, admin, order):
    for value in (OrderStatus.PROCESSING, OrderStatus.SHIPPED):
        await update_order_status(db, admin, order.order_number, value)
    await collect_cash(db, admin, order.order_number)
    await update_order_status(db, admin, order.order_number, OrderStatus.DELIVERED)


def test_checkout_snapshots_ownership_status_and_cancellation(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, other, admin, delivery = users
            order = await buy(db, customer, product_id)
            assert order.status == OrderStatus.PENDING
            assert order.total_price == Decimal("400.00")
            assert order.items[0].subtotal == Decimal("400.00")
            assert (await get_cart(db, customer["id"])).items == []
            assert await db.fetchval("SELECT stock_quantity FROM product") == 8
            await db.execute(
                "UPDATE product SET product_name = 'New name', price = 300"
            )
            fetched = await get_order(db, customer, order.order_number)
            assert fetched.items[0].product_name == "T-shirt"
            assert fetched.items[0].unit_price == Decimal("200.00")
            assert await list_orders(db, other) == []
            with pytest.raises(APIException) as error:
                await get_order(db, other, order.order_number)
            assert error.value.status_code == 404
            with pytest.raises(APIException) as error:
                await update_order_status(
                    db, customer, order.order_number, OrderStatus.DELIVERED
                )
            assert error.value.status_code == 403
            with pytest.raises(APIException) as error:
                await update_order_status(
                    db, admin, order.order_number, OrderStatus.DELIVERED
                )
            assert error.value.status_code == 409
            with pytest.raises(APIException) as error:
                await update_order_status(
                    db, delivery, order.order_number, OrderStatus.CANCELLED
                )
            assert error.value.status_code == 403
            for _ in range(2):
                cancelled = await update_order_status(
                    db, customer, order.order_number, OrderStatus.CANCELLED
                )
                assert cancelled.status == OrderStatus.CANCELLED
            assert await db.fetchval("SELECT stock_quantity FROM product") == 10

    asyncio.run(scenario())


def test_failed_checkout_rolls_back_and_competing_checkouts_do_not_oversell(
    database_url,
):
    async def scenario():
        async with commerce_database(database_url) as (db, schema, users, product_id):
            first, second = users[:2]
            for user in (first, second):
                await add_to_cart(
                    db, user["id"], AddToCartRequest(product_id=product_id, quantity=8)
                )
            other_db = await asyncpg.connect(database_url)
            try:
                await other_db.execute(f'SET search_path TO "{schema}"')
                results = await asyncio.wait_for(
                    asyncio.gather(
                        checkout(db, first, CheckoutRequest(shipping_address="Cairo")),
                        checkout(
                            other_db, second, CheckoutRequest(shipping_address="Giza")
                        ),
                        return_exceptions=True,
                    ),
                    timeout=10,
                )
                errors = [value for value in results if isinstance(value, APIException)]
                assert len(errors) == 1 and errors[0].status_code == 409
                assert await db.fetchval('SELECT count(*) FROM "order"') == 1
                assert await db.fetchval("SELECT stock_quantity FROM product") == 2
                assert await db.fetchval("SELECT sum(quantity) FROM cart_item") == 8
                assert await db.fetchval("SELECT count(*) FROM order_item") == 1
            finally:
                await other_db.close()

    asyncio.run(scenario())


def test_empty_cart_and_paid_cancellation(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, _, admin, _ = users
            with pytest.raises(APIException) as error:
                await checkout(db, customer, CheckoutRequest(shipping_address="Cairo"))
            assert error.value.status_code == 400
            order = await buy(db, customer, product_id)
            await db.execute(
                "UPDATE payment SET payment_status = 'COMPLETED' WHERE order_id = $1",
                order.id,
            )
            with pytest.raises(APIException) as error:
                await update_order_status(
                    db, admin, order.order_number, OrderStatus.CANCELLED
                )
            assert error.value.status_code == 409
            assert await db.fetchval("SELECT stock_quantity FROM product") == 8
            assert (
                await get_order(db, customer, order.order_number)
            ).status == OrderStatus.PENDING

    asyncio.run(scenario())


def test_verified_reviews_and_report_moderation(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, other, admin, _ = users
            request = ReviewCreate(product_id=product_id, rating=5, comment="Great")
            with pytest.raises(APIException) as error:
                await create_review(db, customer, request)
            assert error.value.status_code == 403
            order = await buy(db, customer, product_id)
            await deliver(db, admin, order)
            retried = await update_order_status(
                db, users[3], order.order_number, OrderStatus.DELIVERED
            )
            assert retried.status == OrderStatus.DELIVERED
            review = await create_review(db, customer, request)
            assert (
                (await get_order(db, customer, order.order_number)).items[0].is_reviewed
            )
            with pytest.raises(APIException) as error:
                await create_review(db, customer, request)
            assert error.value.status_code == 409
            with pytest.raises(APIException) as error:
                await update_review(
                    db, other["id"], review.id, ReviewUpdate(rating=1, comment="Bad")
                )
            assert error.value.status_code == 404
            edited = await update_review(
                db, customer["id"], review.id, ReviewUpdate(rating=4, comment="Good")
            )
            assert edited.rating == 4
            assert len(await list_reviews(db, product_id)) == 1
            product_report = await create_report(
                db,
                other["id"],
                ReportCreate(product_id=product_id, reason="Incorrect description"),
            )
            report = await create_report(
                db, other["id"], ReportCreate(review_id=review.id, reason="Spam")
            )
            with pytest.raises(APIException) as error:
                await create_report(
                    db, other["id"], ReportCreate(review_id=review.id, reason="Spam")
                )
            assert error.value.status_code == 409
            assert await list_reports(db, customer) == []
            assert len(await list_reports(db, other)) == 2
            assert len(await list_reports(db, admin)) == 2
            with pytest.raises(APIException) as error:
                await get_report(db, customer, report.id)
            assert error.value.status_code == 404
            with pytest.raises(APIException) as error:
                await update_report(
                    db,
                    other,
                    report.id,
                    ReportUpdate(status="resolved", resolution="Removed"),
                )
            assert error.value.status_code == 403
            await delete_review(db, admin, review.id)
            preserved = await get_report(db, admin, report.id)
            assert preserved.review_id is None
            assert (
                not (await get_order(db, customer, order.order_number))
                .items[0]
                .is_reviewed
            )
            closed = await update_report(
                db,
                admin,
                report.id,
                ReportUpdate(status="resolved", resolution="Removed spam"),
            )
            assert closed.status == ReportStatus.RESOLVED
            assert (await get_report(db, other, report.id)).resolution == "Removed spam"
            with pytest.raises(APIException) as error:
                await update_report(
                    db,
                    admin,
                    report.id,
                    ReportUpdate(status="dismissed", resolution="Ignore"),
                )
            assert error.value.status_code == 409
            await update_report(
                db,
                admin,
                product_report.id,
                ReportUpdate(status="dismissed", resolution="Description correct"),
            )

    asyncio.run(scenario())


def test_sales_only_include_delivered_orders_and_use_creation_period(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, _, admin, _ = users
            empty = await sales_report(db, SalesPeriod())
            assert empty.total_orders == 0 and empty.delivered_sales == 0
            delivered = await buy(db, customer, product_id)
            await deliver(db, admin, delivered)
            await buy(db, customer, product_id)
            cancelled = await buy(db, customer, product_id)
            await update_order_status(
                db, customer, cancelled.order_number, OrderStatus.CANCELLED
            )
            report = await sales_report(db, SalesPeriod())
            assert report.total_orders == 3
            assert report.delivered_sales == Decimal("400.00")
            assert report.average_delivered_order_value == Decimal("400.00")
            assert report.top_products[0].quantity == 2
            assert report.top_products[0].sales == Decimal("400.00")
            future = await sales_report(
                db, SalesPeriod(start=datetime.now(timezone.utc) + timedelta(days=1))
            )
            assert future.total_orders == 0

    asyncio.run(scenario())


def test_new_migrations_downgrade_and_upgrade(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, _, _):
            for name in (
                "b5e02f3c8d41_customer_reports",
                "a4d91e2b7c30_order_review_integrity",
            ):
                path = Path("migrations/versions") / f"{name}.py"
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                statements = []
                module.op = SimpleNamespace(execute=statements.append)
                module.downgrade()
                for statement in statements:
                    await db.execute(statement)
            for name in (
                "a4d91e2b7c30_order_review_integrity",
                "b5e02f3c8d41_customer_reports",
            ):
                spec = importlib.util.spec_from_file_location(
                    name, Path("migrations/versions") / f"{name}.py"
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                statements = []
                module.op = SimpleNamespace(execute=statements.append)
                module.upgrade()
                for statement in statements:
                    await db.execute(statement)
            assert await db.fetchval("SELECT count(*) FROM report") == 0

    asyncio.run(scenario())


def test_failure_after_order_insert_rolls_back_entire_checkout(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer = users[0]
            await add_to_cart(
                db, customer["id"], AddToCartRequest(product_id=product_id, quantity=2)
            )
            await db.execute(
                "ALTER TABLE order_item ADD CONSTRAINT test_rejection "
                "CHECK (quantity < 2)"
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await checkout(db, customer, CheckoutRequest(shipping_address="Cairo"))
            assert await db.fetchval('SELECT count(*) FROM "order"') == 0
            assert await db.fetchval("SELECT stock_quantity FROM product") == 10
            assert (await get_cart(db, customer["id"])).total_quantity == 2

    asyncio.run(scenario())


def test_concurrent_checkout_of_same_cart_and_cancellation_are_safe(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, schema, users, product_id):
            customer = users[0]
            await add_to_cart(
                db, customer["id"], AddToCartRequest(product_id=product_id, quantity=2)
            )
            second = await asyncpg.connect(database_url)
            try:
                await second.execute(f'SET search_path TO "{schema}"')
                results = await asyncio.wait_for(
                    asyncio.gather(
                        checkout(
                            db, customer, CheckoutRequest(shipping_address="Cairo")
                        ),
                        checkout(
                            second, customer, CheckoutRequest(shipping_address="Cairo")
                        ),
                        return_exceptions=True,
                    ),
                    timeout=10,
                )
                orders = [
                    result for result in results if not isinstance(result, Exception)
                ]
                assert len(orders) == 1
                assert sum(isinstance(result, APIException) for result in results) == 1
                number = orders[0].order_number
                await asyncio.wait_for(
                    asyncio.gather(
                        update_order_status(
                            db, customer, number, OrderStatus.CANCELLED
                        ),
                        update_order_status(
                            second, customer, number, OrderStatus.CANCELLED
                        ),
                    ),
                    timeout=10,
                )
                assert await db.fetchval("SELECT stock_quantity FROM product") == 10
            finally:
                await second.close()

    asyncio.run(scenario())


def test_duplicate_reviews_race_and_partial_update(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, schema, users, product_id):
            customer, _, admin, _ = users
            order = await buy(db, customer, product_id)
            await deliver(db, admin, order)
            second = await asyncpg.connect(database_url)
            try:
                await second.execute(f'SET search_path TO "{schema}"')
                request = ReviewCreate(product_id=product_id, rating=5, comment="Great")
                results = await asyncio.wait_for(
                    asyncio.gather(
                        create_review(db, customer, request),
                        create_review(second, customer, request),
                        return_exceptions=True,
                    ),
                    timeout=10,
                )
                errors = [
                    result for result in results if isinstance(result, APIException)
                ]
                assert len(errors) == 1 and errors[0].status_code == 409
                review = (await list_reviews(db, product_id))[0]
                updated = await update_review(
                    db, customer["id"], review.id, ReviewUpdate(rating=3)
                )
                assert updated.rating == 3 and updated.comment == "Great"
                with pytest.raises(APIException) as error:
                    await delete_review(db, users[1], review.id)
                assert error.value.status_code == 404
            finally:
                await second.close()

    asyncio.run(scenario())
