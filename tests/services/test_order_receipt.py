import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.exceptions import APIException
from app.services.order import get_order_receipt, order_receipt_token


class ReceiptConnection:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, query, order_number):
        assert "created_at > NOW() - INTERVAL '30 days'" in query
        assert order_number == self.row["order_number"]
        return self.row


def test_receipt_requires_the_order_specific_capability():
    order_id = uuid4()
    other_id = uuid4()
    db = ReceiptConnection(
        {
            "id": order_id,
            "order_number": 42,
            "total_price": Decimal("220.00"),
            "currency": "EGP",
            "recipient_name": "Vee Buyer",
            "recipient_phone": "01012345678",
            "shipping_address": "Cairo",
            "delivery_area": "Cairo",
        }
    )

    receipt = asyncio.run(get_order_receipt(db, 42, order_receipt_token(order_id)))
    assert receipt.order_number == 42
    assert receipt.recipient_name == "Vee Buyer"
    assert "guest_email" not in receipt.model_dump()

    with pytest.raises(APIException) as error:
        asyncio.run(get_order_receipt(db, 42, order_receipt_token(other_id)))
    assert error.value.status_code == 404
