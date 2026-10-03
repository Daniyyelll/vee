import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.enums import DeliveryArea
from app.schemas.order import CheckoutRequest, GuestCheckoutRequest
from app.schemas.user import UserCreate, UserUpdate
from app.services import order as order_service


def test_checkout_requires_one_name_and_phone_for_all_customers():
    with pytest.raises(ValidationError):
        CheckoutRequest(shipping_address="Cairo", delivery_area="Cairo")
    contact = {"name": "Vee Customer", "phone": "01012345678"}
    registered = CheckoutRequest(
        **contact, shipping_address="Cairo", delivery_area="Cairo"
    )
    guest = GuestCheckoutRequest(
        **contact,
        shipping_address="Cairo",
        delivery_area="Cairo",
        email="guest@example.com",
        items=[{"productId": str(uuid4()), "quantity": 1}],
    )
    assert registered.name == guest.name == "Vee Customer"
    assert registered.phone == guest.phone == "01012345678"
    assert registered.delivery_area == guest.delivery_area == DeliveryArea.CAIRO
    for bad_area in ("Alexandria", "", "cairo"):
        with pytest.raises(ValidationError):
            CheckoutRequest(
                **contact, shipping_address="Street 12", delivery_area=bad_area
            )
    with pytest.raises(ValidationError):
        CheckoutRequest(**contact, shipping_address="Street 12")


def test_profile_phone_is_optional_and_trims_input():
    account = UserCreate(
        name="Buyer", email="buyer@example.com", password="long-secret-password"
    )
    assert account.phone is None
    assert UserUpdate(phone=" 01012345678 ").phone == "01012345678"
    with pytest.raises(ValidationError):
        UserUpdate(phone=" 123 ")


def test_order_insert_saves_delivery_contact_independently(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(
        order_service, "redeem_coupon", AsyncMock(return_value=(None, None, Decimal(0)))
    )
    monkeypatch.setattr(order_service, "insert_cash_payment", AsyncMock())
    monkeypatch.setattr(order_service, "enqueue_email", AsyncMock())
    monkeypatch.setattr(
        order_service, "_read_orders", AsyncMock(return_value=["order"])
    )
    user_id = uuid4()
    item = {
        "product_id": uuid4(),
        "product_name": "Lip Balm",
        "price": Decimal("170.00"),
        "quantity": 1,
        "stock_quantity": 5,
        "active": True,
        "currency": "EGP",
    }

    result = asyncio.run(
        order_service._create_order(
            db,
            [item],
            "Cairo",
            None,
            user_id=user_id,
            recipient_name="Delivery Recipient",
            recipient_phone="01012345678",
            delivery_area=DeliveryArea.CAIRO,
        )
    )

    assert result == "order"
    insert = next(
        call.args
        for call in db.execute.call_args_list
        if 'INSERT INTO "order"' in call.args[0]
    )
    assert "recipient_name" in insert[0] and "recipient_phone" in insert[0]
    assert "delivery_area" in insert[0]
    assert insert[-8] == "Cairo"
    assert insert[-3:-1] == ("Delivery Recipient", "01012345678")
