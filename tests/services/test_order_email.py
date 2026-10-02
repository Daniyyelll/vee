import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

from app.schemas.order import OrderItemRead, OrderRead
from app.services import email as email_service, order as order_service, outbox


def test_order_email_uses_snapshot_and_escapes_customer_input(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(email_service.aiosmtplib, "send", send)
    order = OrderRead(
        id=uuid4(),
        order_number=123,
        total_price=Decimal("200.00"),
        status="shipped",
        user={"name": "Buyer", "email": "buyer@example.com", "role": "customer"},
        shipping_address="<script>bad</script>",
        created_at=datetime.now(timezone.utc),
        items=[
            OrderItemRead(
                id=uuid4(),
                product_id=uuid4(),
                product_name="T-shirt",
                quantity=1,
                unit_price=Decimal("200.00"),
                is_reviewed=False,
            )
        ],
    )
    asyncio.run(
        email_service.send_order_status_update_email(
            "buyer@example.com", "Buyer", order
        )
    )
    message = send.await_args.args[0]
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "#123" in html and "T-shirt" in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "Order Total" in html


def test_order_confirmation_failure_is_best_effort(monkeypatch):
    monkeypatch.setattr(
        email_service.aiosmtplib,
        "send",
        AsyncMock(side_effect=RuntimeError("SMTP unavailable")),
    )
    order = OrderRead(
        id=uuid4(),
        order_number=123,
        total_price=Decimal("200.00"),
        status="pending",
        user={"name": "Buyer", "email": "buyer@example.com", "role": "customer"},
        shipping_address="Cairo",
        created_at=datetime.now(timezone.utc),
    )
    asyncio.run(
        email_service.send_order_confirmation_email("buyer@example.com", "Buyer", order)
    )


def test_queued_order_email_uses_saved_delivery_name(monkeypatch):
    db = AsyncMock()
    order_id = uuid4()
    db.fetchrow.return_value = {"id": order_id}
    saved_order = OrderRead(
        id=order_id,
        order_number=123,
        total_price=Decimal("200.00"),
        status="pending",
        user={
            "name": "Changed Profile",
            "email": "buyer@example.com",
            "role": "customer",
        },
        recipient_name="Delivery Recipient",
        recipient_phone="01012345678",
        shipping_address="Cairo",
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        order_service, "_read_orders", AsyncMock(return_value=[saved_order])
    )
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "send_order_confirmation_email", send)

    assert asyncio.run(
        outbox._send(db, "order_confirmation", {"order_id": str(order_id)})
    )
    assert send.await_args.args[1] == "Delivery Recipient"
