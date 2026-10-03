"""Exercise real SQL in isolated schemas; never modify application tables."""

import asyncio
import importlib.util
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest

from app.core.exceptions import APIException
from app.domain.enums import OrderStatus, ReportStatus, UserRole
from app.schemas.cart import AddToCartRequest
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.schemas.coupon import CouponCreate
from app.schemas.order import CheckoutRequest, GuestCheckoutItem, GuestCheckoutRequest
from app.schemas.payment import CashRefundRequest
from app.schemas.report import ReportCreate, ReportUpdate, SalesPeriod
from app.schemas.review import ReviewCreate, ReviewUpdate
from app.services import outbox as outbox_service
from app.services.cart import add_to_cart, get_cart
from app.services.category import (
    create_category,
    get_category_id_from_slug,
    update_category,
)
from app.services.coupon import create_coupon, list_coupons
from app.services.order import (
    assign_order_delivery,
    checkout,
    expire_pending_orders,
    get_order,
    guest_checkout,
    list_orders,
    quote_cart_order,
    quote_guest_order,
    update_order_status,
)
from app.services.payment import collect_cash, refund_cash
from app.services.product import delete_product, get_all_products
from app.services.rate_limit import consume_rate_limit
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
from app.services.user import process_forgot_password


@pytest.fixture
def database_url():
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    return value


def migration_modules():
    pending = {}
    for path in Path("migrations/versions").glob("*.py"):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        pending[module.revision] = module

    ordered = []
    applied = set()
    while pending:
        ready = []
        for revision, module in pending.items():
            dependencies = module.down_revision
            if dependencies is None:
                dependencies = ()
            elif isinstance(dependencies, str):
                dependencies = (dependencies,)
            if set(dependencies) <= applied:
                ready.append((revision, module))
        if not ready:
            raise AssertionError("Migration graph has missing dependencies or a cycle")
        for revision, module in sorted(ready):
            ordered.append(module)
            applied.add(revision)
            del pending[revision]
    return ordered


def migration_statements():
    statements = []
    for module in migration_modules():
        module.op = SimpleNamespace(execute=statements.append)
        module.upgrade()
    return [statement for statement in statements if statement.strip()]


def test_populated_catalog_migrates_slugs(database_url):
    async def scenario():
        db = await asyncpg.connect(database_url)
        schema = f"test_migration_{uuid4().hex}"
        try:
            await db.execute(f'CREATE SCHEMA "{schema}"')
            await db.execute(f'SET search_path TO "{schema}"')
            category_id, product_id, user_id, order_id = (
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            )
            for module in migration_modules():
                statements = []
                module.op = SimpleNamespace(execute=statements.append)
                module.upgrade()
                for statement in statements:
                    try:
                        await db.execute(statement)
                    except Exception as exc:
                        raise AssertionError(
                            f"Migration {module.revision} failed: {statement[:120]!r}"
                        ) from exc
                if module.revision == "f2b8c9d7e4a1":
                    await db.execute(
                        "INSERT INTO category (id, category_name) "
                        "VALUES ($1, 'Lip Care')",
                        category_id,
                    )
                    await db.execute(
                        "INSERT INTO product "
                        "(id, product_name, price, stock_quantity, category_id) "
                        "VALUES ($1, 'Lip Balm', 100, 5, $2)",
                        product_id,
                        category_id,
                    )
                if module.revision == "d8c6e3a41b02":
                    await db.execute(
                        'INSERT INTO "user" '
                        "(id, name, email, hashed_password, role, active) "
                        "VALUES ($1, 'Legacy Buyer', 'legacy@example.com', "
                        "'unused', 'CUSTOMER', TRUE)",
                        user_id,
                    )
                    await db.execute(
                        'INSERT INTO "order" '
                        "(id, order_number, total_price, shipping_address, "
                        "status, user_id, subtotal_price, discount_amount, "
                        "shipping_fee) VALUES "
                        "($1, nextval('order_number_seq'), 100, 'Cairo', "
                        "'DELIVERED', $2, 100, 0, 0)",
                        order_id,
                        user_id,
                    )
                    await db.execute(
                        "INSERT INTO payment "
                        "(id, amount, currency, payment_status, payment_method, "
                        "order_id) VALUES ($1, 100, 'SAR', 'COMPLETED', 'CASH', $2)",
                        uuid4(),
                        order_id,
                    )
            assert (
                await db.fetchval(
                    "SELECT product_slug FROM product WHERE id = $1", product_id
                )
            ).startswith("lip-balm-")
            assert await get_category_id_from_slug(db, "lip-care") == category_id
            assert (
                await db.fetchval(
                    'SELECT currency::text FROM "order" WHERE id = $1', order_id
                )
                == "SAR"
            )
        finally:
            try:
                await db.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            finally:
                await db.close()

    asyncio.run(scenario())


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
            "INSERT INTO category (id, category_name, slug) "
            "VALUES ($1, 'Clothes', 'clothes')",
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
    return await checkout(
        db,
        user,
        CheckoutRequest(
            name="Buyer",
            phone="01012345678",
            shipping_address="Cairo",
            delivery_area="Cairo",
        ),
    )


def test_guest_checkout_and_coupon_rules(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            customer, other, admin, _ = users
            percent = await create_coupon(
                db,
                CouponCreate(
                    code="HALF-OFF",
                    kind="percent",
                    discount_percent=50,
                    assigned_user_id=customer["id"],
                ),
            )
            assert percent.code == "HALF-OFF"
            guest_request = GuestCheckoutRequest(
                name="Guest Buyer",
                email="guest@example.com",
                phone="01012345678",
                shipping_address="Cairo",
                delivery_area="Cairo",
                items=[GuestCheckoutItem(product_id=product_id, quantity=1)],
                coupon_code="HALF-OFF",
            )
            with pytest.raises(APIException) as error:
                await guest_checkout(db, guest_request, "invalid-coupon-request")
            assert error.value.status_code == 403
            assert await db.fetchval('SELECT count(*) FROM "order"') == 0

            free = await create_coupon(
                db,
                CouponCreate(
                    code="FREE-SHIP",
                    kind="free_shipping",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                ),
            )
            guest_request.coupon_code = free.code
            guest_quote = await quote_guest_order(
                db, guest_request.items, guest_request.coupon_code
            )
            assert guest_quote.total_price == Decimal("200.00")
            assert (await list_coupons(db))[0].uses_count == 0
            assert await db.fetchval('SELECT count(*) FROM "order"') == 0
            order = await guest_checkout(db, guest_request, "test-request-123")
            assert order.user is None
            assert order.guest_email == "guest@example.com"
            assert order.shipping_fee == Decimal("50.00")
            assert order.discount_amount == Decimal("50.00")
            assert order.total_price == Decimal("200.00")
            assert order.payment.amount == order.total_price
            assert await db.fetchval("SELECT stock_quantity FROM product") == 9
            replay = await guest_checkout(db, guest_request, "test-request-123")
            assert replay.id == order.id
            assert await db.fetchval('SELECT count(*) FROM "order"') == 1
            assert await db.fetchval("SELECT stock_quantity FROM product") == 9
            guest_request.phone = "01112345678"
            with pytest.raises(APIException) as reused:
                await guest_checkout(db, guest_request, "test-request-123")
            assert reused.value.status_code == 409
            guest_request.phone = "01012345678"
            stored = await get_order(db, admin, order.order_number)
            assert stored.guest_name == "Guest Buyer"
            with pytest.raises(APIException) as error:
                await get_order(db, other, order.order_number)
            assert error.value.status_code == 404

            await add_to_cart(
                db, customer["id"], AddToCartRequest(product_id=product_id, quantity=1)
            )
            cart_quote = await quote_cart_order(db, customer["id"], "half-off")
            assert cart_quote.total_price == Decimal("150.00")
            discounted = await checkout(
                db,
                customer,
                CheckoutRequest(
                    name="Buyer",
                    phone="01012345678",
                    shipping_address="Cairo",
                    delivery_area="Cairo",
                    coupon_code="half-off",
                ),
            )
            assert discounted.subtotal_price == Decimal("200.00")
            assert discounted.discount_amount == Decimal("100.00")
            assert discounted.total_price == Decimal("150.00")
            assert discounted.total_price == cart_quote.total_price

    asyncio.run(scenario())


def test_shared_coupon_limit_and_cancellation(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            admin = users[2]
            coupon = await create_coupon(
                db,
                CouponCreate(code="FRIENDS2", kind="free_shipping", max_uses=2),
            )
            assert coupon.uses_count == 0
            assert coupon.remaining_uses == 2
            assert coupon.model_dump(by_alias=True)["remainingUses"] == 2

            async def place(email: str, key: str):
                return await guest_checkout(
                    db,
                    GuestCheckoutRequest(
                        name="Friend",
                        email=email,
                        phone="01012345678",
                        shipping_address="Cairo",
                        delivery_area="Cairo",
                        coupon_code="FRIENDS2",
                        items=[GuestCheckoutItem(product_id=product_id, quantity=1)],
                    ),
                    key,
                )

            first = await place("first@example.com", "friend-first-request")
            await place("second@example.com", "friend-second-request")
            assert (await list_coupons(db))[0].remaining_uses == 0
            with pytest.raises(APIException) as exhausted:
                await place("third@example.com", "friend-third-request")
            assert exhausted.value.status_code == 409
            assert await db.fetchval('SELECT count(*) FROM "order"') == 2
            await update_order_status(
                db, admin, first.order_number, OrderStatus.CANCELLED
            )
            assert (await list_coupons(db))[0].remaining_uses == 1
            await place("third@example.com", "friend-third-request")
            assert (await list_coupons(db))[0].uses_count == 2

    asyncio.run(scenario())


def test_one_use_coupon_serializes_concurrent_guests(database_url):
    async def scenario():
        async with commerce_database(database_url) as (
            db,
            schema,
            _,
            first_product_id,
        ):
            coupon = await create_coupon(
                db,
                CouponCreate(
                    code="ONEFRIEND", kind="percent", discount_percent=10, max_uses=1
                ),
            )
            second_product_id = uuid4()
            category_id = await db.fetchval("SELECT category_id FROM product LIMIT 1")
            await db.execute(
                """
                INSERT INTO product (
                    id, product_name, price, stock_quantity, category_id, product_slug
                ) VALUES ($1, 'Scarf', 100, 10, $2, 'scarf')
                """,
                second_product_id,
                category_id,
            )
            second = await asyncpg.connect(database_url)
            try:
                await second.execute(f'SET search_path TO "{schema}"')

                async def place(connection, product_id, email, key):
                    return await guest_checkout(
                        connection,
                        GuestCheckoutRequest(
                            name="Friend",
                            email=email,
                            phone="01012345678",
                            shipping_address="Cairo",
                            delivery_area="Cairo",
                            coupon_code=coupon.code,
                            items=[
                                GuestCheckoutItem(product_id=product_id, quantity=1)
                            ],
                        ),
                        key,
                    )

                results = await asyncio.wait_for(
                    asyncio.gather(
                        place(db, first_product_id, "a@example.com", "one-friend-a"),
                        place(
                            second, second_product_id, "b@example.com", "one-friend-b"
                        ),
                        return_exceptions=True,
                    ),
                    timeout=10,
                )
                assert sum(not isinstance(result, Exception) for result in results) == 1
                failures = [
                    result for result in results if isinstance(result, Exception)
                ]
                assert len(failures) == 1
                assert isinstance(failures[0], APIException)
                assert failures[0].status_code == 409
                assert (await list_coupons(db))[0].uses_count == 1
            finally:
                await second.close()

    asyncio.run(scenario())


def test_expiry_restores_stock_and_archived_product_is_hidden(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            order = await buy(db, users[0], product_id, quantity=2)
            assert await db.fetchval("SELECT stock_quantity FROM product") == 8
            await db.execute(
                "UPDATE \"order\" SET expires_at = NOW() - INTERVAL '1 second' "
                "WHERE id = $1",
                order.id,
            )
            assert await expire_pending_orders(db) == 1
            assert await expire_pending_orders(db) == 0
            assert await db.fetchval("SELECT stock_quantity FROM product") == 10
            assert (await get_order(db, users[2], order.order_number)).status == (
                OrderStatus.CANCELLED
            )
            await delete_product(db, "t-shirt")
            assert await get_all_products(db) == []
            with pytest.raises(APIException) as unavailable:
                await add_to_cart(
                    db,
                    users[0]["id"],
                    AddToCartRequest(product_id=product_id, quantity=1),
                )
            assert unavailable.value.status_code == 409

    asyncio.run(scenario())


def test_category_slug_collision_uses_stable_indexed_lookup(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, _, _):
            first = await create_category(db, CategoryCreate(category_name="Lip Care"))
            second = await create_category(db, CategoryCreate(category_name="lip care"))
            assert first["slug"] == "lip-care"
            assert second["slug"].startswith("lip-care-")
            assert await get_category_id_from_slug(db, first["slug"]) == first["id"]
            assert await get_category_id_from_slug(db, second["slug"]) == second["id"]
            edited = await update_category(
                db, first["id"], CategoryUpdate(description=None)
            )
            assert edited["slug"] == first["slug"]

    asyncio.run(scenario())


def test_password_reset_email_is_encrypted_and_retried(database_url, monkeypatch):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, _):
            customer = users[0]
            await process_forgot_password(db, customer["email"])
            queued = await db.fetchrow(
                "SELECT id, payload FROM email_outbox WHERE kind = 'password_reset'"
            )
            assert "sealed" in queued["payload"]
            assert customer["email"] not in str(queued["payload"])
            deliver = AsyncMock(side_effect=[False, True])
            monkeypatch.setattr(outbox_service, "send_reset_password_email", deliver)
            assert await outbox_service.process_email_outbox(db) == 0
            assert (
                await db.fetchval(
                    "SELECT attempts FROM email_outbox WHERE id = $1", queued["id"]
                )
                == 1
            )
            await db.execute(
                "UPDATE email_outbox SET next_attempt_at = NOW() WHERE id = $1",
                queued["id"],
            )
            assert await outbox_service.process_email_outbox(db) == 1
            assert (
                await db.fetchval(
                    "SELECT payload FROM email_outbox WHERE id = $1", queued["id"]
                )
                == "{}"
            )
            assert deliver.await_count == 2

    asyncio.run(scenario())


def test_order_confirmation_is_delivered_from_outbox(database_url, monkeypatch):
    async def scenario():
        async with commerce_database(database_url) as (db, _, users, product_id):
            order = await buy(db, users[0], product_id)
            deliver = AsyncMock(return_value=True)
            monkeypatch.setattr(
                outbox_service, "send_order_confirmation_email", deliver
            )
            assert await outbox_service.process_email_outbox(db) == 1
            assert deliver.await_args.args[2].id == order.id
            assert (
                await db.fetchval(
                    "SELECT count(*) FROM email_outbox WHERE sent_at IS NOT NULL"
                )
                == 1
            )

    asyncio.run(scenario())


def test_database_rate_limit_blocks_excess_requests(database_url):
    async def scenario():
        async with commerce_database(database_url) as (db, _, _, _):
            for _ in range(2):
                await consume_rate_limit(
                    db,
                    "guest-checkout-test",
                    "127.0.0.1",
                    limit=2,
                    window_seconds=3600,
                )
            with pytest.raises(APIException) as limited:
                await consume_rate_limit(
                    db,
                    "guest-checkout-test",
                    "127.0.0.1",
                    limit=2,
                    window_seconds=3600,
                )
            assert limited.value.status_code == 429

    asyncio.run(scenario())


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
            assert order.total_price == Decimal("450.00")
            assert order.shipping_fee == Decimal("50.00")
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
            assert await list_orders(db, delivery) == []
            with pytest.raises(APIException) as error:
                await get_order(db, other, order.order_number)
            assert error.value.status_code == 404
            with pytest.raises(APIException) as error:
                await get_order(db, delivery, order.order_number)
            assert error.value.status_code == 404

            assigned = await assign_order_delivery(
                db, admin, order.order_number, delivery["id"]
            )
            assert assigned.delivery_user_id == delivery["id"]
            assert (await get_order(db, delivery, order.order_number)).id == order.id
            assert [value.id for value in await list_orders(db, delivery)] == [order.id]
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
                        checkout(
                            db,
                            first,
                            CheckoutRequest(
                                name="Buyer",
                                phone="01012345678",
                                shipping_address="Cairo",
                                delivery_area="Cairo",
                            ),
                        ),
                        checkout(
                            other_db,
                            second,
                            CheckoutRequest(
                                name="Buyer",
                                phone="01012345678",
                                shipping_address="Giza",
                                delivery_area="Giza",
                            ),
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
            customer, other, admin, delivery = users
            request = ReviewCreate(product_id=product_id, rating=5, comment="Great")
            with pytest.raises(APIException) as error:
                await create_review(db, customer, request)
            assert error.value.status_code == 403
            order = await buy(db, customer, product_id)
            await assign_order_delivery(db, admin, order.order_number, delivery["id"])
            await deliver(db, admin, order)
            retried = await update_order_status(
                db, delivery, order.order_number, OrderStatus.DELIVERED
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
            assert report.delivered_sales == Decimal("450.00")
            assert report.average_delivered_order_value == Decimal("450.00")
            assert report.top_products[0].quantity == 2
            assert report.top_products[0].sales == Decimal("400.00")
            await refund_cash(
                db,
                admin,
                delivered.order_number,
                CashRefundRequest(reason="Cash returned to customer"),
            )
            after_refund = await sales_report(db, SalesPeriod())
            assert after_refund.delivered_sales == Decimal("450.00")
            assert after_refund.refunded_amount == Decimal("450.00")
            assert after_refund.net_sales == Decimal("0.00")
            assert after_refund.top_products == []
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
                            db,
                            customer,
                            CheckoutRequest(
                                name="Buyer",
                                phone="01012345678",
                                shipping_address="Cairo",
                                delivery_area="Cairo",
                            ),
                        ),
                        checkout(
                            second,
                            customer,
                            CheckoutRequest(
                                name="Buyer",
                                phone="01012345678",
                                shipping_address="Cairo",
                                delivery_area="Cairo",
                            ),
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
