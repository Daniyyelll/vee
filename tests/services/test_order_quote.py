import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import APIException
from app.schemas.order import GuestCheckoutItem, OrderQuote, QuoteItemRead
from app.services import order as order_service
from app.services.order import quote_cart_order, quote_guest_order


def product_row(product_id):
    return {
        "product_id": product_id,
        "product_name": "Lip Balm",
        "price": Decimal("170.00"),
        "stock_quantity": 5,
        "active": True,
        "currency": "EGP",
    }


def test_guest_quote_prices_discount_without_creating_or_reserving():
    product_id = uuid4()
    db = AsyncMock()
    db.fetch.return_value = [product_row(product_id)]
    db.fetchrow.return_value = {
        "id": uuid4(),
        "code": "TENOFF",
        "kind": "percent",
        "discount_percent": Decimal("10"),
        "active": True,
        "starts_at": None,
        "expires_at": None,
        "assigned_user_id": None,
        "max_uses": None,
    }
    db.fetchval.return_value = datetime.now(timezone.utc)

    quote = asyncio.run(
        quote_guest_order(
            db,
            [GuestCheckoutItem(product_id=product_id, quantity=2)],
            "tenoff",
        )
    )

    assert quote.subtotal_price == Decimal("340.00")
    assert quote.shipping_fee == Decimal("50.00")
    assert quote.discount_amount == Decimal("34.00")
    assert quote.total_price == Decimal("356.00")
    assert quote.items[0].subtotal == Decimal("340.00")
    assert quote.coupon_code == "TENOFF"
    assert "FOR UPDATE" not in db.fetchrow.call_args.args[0]
    db.execute.assert_not_awaited()
    db.executemany.assert_not_awaited()


def test_customer_coupon_requires_authenticated_cart_quote():
    product_id, customer_id = uuid4(), uuid4()
    db = AsyncMock()
    db.fetch.return_value = [{**product_row(product_id), "quantity": 1}]
    db.fetchrow.return_value = {
        "id": uuid4(),
        "code": "PRIVATE",
        "kind": "free_shipping",
        "discount_percent": None,
        "active": True,
        "starts_at": None,
        "expires_at": None,
        "assigned_user_id": customer_id,
        "max_uses": None,
    }
    db.fetchval.return_value = datetime.now(timezone.utc)

    with pytest.raises(APIException) as forbidden:
        asyncio.run(
            quote_guest_order(
                db, [GuestCheckoutItem(product_id=product_id, quantity=1)], "PRIVATE"
            )
        )
    assert forbidden.value.status_code == 403

    quote = asyncio.run(quote_cart_order(db, customer_id, "PRIVATE"))
    assert quote.discount_amount == Decimal("50.00")
    assert quote.total_price == Decimal("170.00")
    db.execute.assert_not_awaited()


def test_guest_quote_rejects_duplicate_items_before_database_access():
    product_id = uuid4()
    db = AsyncMock()
    item = GuestCheckoutItem(product_id=product_id, quantity=1)
    with pytest.raises(APIException):
        asyncio.run(quote_guest_order(db, [item, item], None))
    db.fetch.assert_not_awaited()


def test_checkout_rejects_changed_total_before_reserving_stock(monkeypatch):
    product_id = uuid4()
    quote = OrderQuote(
        items=[
            QuoteItemRead(
                product_id=product_id,
                product_name="Lip Balm",
                quantity=1,
                unit_price=Decimal("170.00"),
                subtotal=Decimal("170.00"),
            )
        ],
        subtotal_price=Decimal("170.00"),
        shipping_fee=Decimal("50.00"),
        discount_amount=Decimal("0.00"),
        total_price=Decimal("220.00"),
        coupon_code=None,
        currency="EGP",
    )
    monkeypatch.setattr(
        order_service, "_price_items", AsyncMock(return_value=(quote, None))
    )
    db = AsyncMock()
    with pytest.raises(APIException) as changed:
        asyncio.run(
            order_service._create_order(
                db,
                [{**product_row(product_id), "quantity": 1}],
                "Cairo",
                None,
                recipient_name="Buyer",
                recipient_phone="01012345678",
                delivery_area="Cairo",
                expected_total=Decimal("210.00"),
            )
        )
    assert changed.value.status_code == 409
    db.execute.assert_not_awaited()
    db.executemany.assert_not_awaited()
