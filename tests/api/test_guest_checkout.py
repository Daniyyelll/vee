from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import order as order_api
from app.db.session import get_connection
from app.schemas.order import OrderRead, OrderReceiptRead


def test_guest_checkout_is_public_and_requires_idempotency_key(monkeypatch):
    app = FastAPI()
    app.include_router(order_api.router)
    app.dependency_overrides[get_connection] = lambda: object()
    order = OrderRead(
        id=uuid4(),
        order_number=123,
        guest_name="Guest Buyer",
        guest_email="guest@example.com",
        guest_phone="01012345678",
        recipient_name="Guest Buyer",
        recipient_phone="01012345678",
        total_price=Decimal("250.00"),
        shipping_address="Cairo",
        delivery_area="Cairo",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    place = AsyncMock(return_value=order)
    monkeypatch.setattr(order_api, "guest_checkout", place)

    response = TestClient(app).post(
        "/orders/guest-checkout",
        headers={"Idempotency-Key": "test-request-123"},
        json={
            "name": "Guest Buyer",
            "email": "guest@example.com",
            "phone": "01012345678",
            "shippingAddress": "Cairo",
            "deliveryArea": "Cairo",
            "items": [{"productId": str(uuid4()), "quantity": 1}],
        },
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["user"] is None
    assert response.json()["data"]["guestEmail"] == "guest@example.com"
    assert response.json()["data"]["recipientName"] == "Guest Buyer"
    assert response.json()["data"]["recipientPhone"] == "01012345678"
    assert response.json()["data"]["deliveryArea"] == "Cairo"
    assert len(response.json()["data"]["receiptToken"]) == 64
    place.assert_awaited_once()
    assert place.await_args.args[2] == "test-request-123"


def test_receipt_requires_token_and_returns_no_store(monkeypatch):
    app = FastAPI()
    app.include_router(order_api.router)
    app.dependency_overrides[get_connection] = lambda: object()
    monkeypatch.setattr(order_api, "consume_rate_limit", AsyncMock())
    receipt = OrderReceiptRead(
        order_number=123,
        total_price=Decimal("250.00"),
        currency="EGP",
        recipient_name="Guest Buyer",
        recipient_phone="01012345678",
        shipping_address="Cairo",
        delivery_area="Cairo",
    )
    read = AsyncMock(return_value=receipt)
    monkeypatch.setattr(order_api, "get_order_receipt", read)
    client = TestClient(app)

    assert client.get("/orders/receipt/123").status_code == 422
    response = client.get("/orders/receipt/123", headers={"Receipt-Token": "a" * 64})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["recipientName"] == "Guest Buyer"
    assert "guestEmail" not in response.json()["data"]
    read.assert_awaited_once()
