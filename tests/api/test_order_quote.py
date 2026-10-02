from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import order as order_api
from app.api.dependencies import get_current_user
from app.db.session import get_connection
from app.schemas.order import OrderQuote, QuoteItemRead


def test_guest_quote_is_public_and_cart_quote_uses_customer_identity(monkeypatch):
    app = FastAPI()
    app.include_router(order_api.router)
    db = object()
    app.dependency_overrides[get_connection] = lambda: db
    customer_id, product_id = uuid4(), uuid4()
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
    guest = AsyncMock(return_value=quote)
    cart = AsyncMock(return_value=quote)
    rate_limit = AsyncMock()
    monkeypatch.setattr(order_api, "quote_guest_order", guest)
    monkeypatch.setattr(order_api, "quote_cart_order", cart)
    monkeypatch.setattr(order_api, "consume_rate_limit", rate_limit)
    client = TestClient(app)

    response = client.post(
        "/orders/quote",
        json={"items": [{"productId": str(product_id), "quantity": 1}]},
    )
    assert response.status_code == 200
    assert response.json()["data"]["totalPrice"] == "220.00"
    assert response.json()["data"]["items"][0]["productName"] == "Lip Balm"
    guest.assert_awaited_once()
    rate_limit.assert_awaited_once()
    assert client.post("/orders/cart-quote", json={}).status_code in (401, 403)

    app.dependency_overrides[get_current_user] = lambda: {"id": customer_id}
    response = client.post("/orders/cart-quote", json={"couponCode": "PRIVATE"})
    assert response.status_code == 200
    cart.assert_awaited_once_with(db, customer_id, "PRIVATE")
