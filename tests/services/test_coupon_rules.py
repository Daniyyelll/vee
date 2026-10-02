import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import APIException
from app.schemas.coupon import CouponCreate
from app.services.coupon import redeem_coupon


class CouponDatabase:
    def __init__(self, coupon):
        self.coupon = coupon

    async def fetchrow(self, _query, _code):
        return self.coupon

    async def fetchval(self, _query):
        return datetime.now(timezone.utc)


def test_coupon_schema_requires_assignment_or_validity_window():
    with pytest.raises(ValidationError):
        CouponCreate(kind="percent", discount_percent=10)
    with pytest.raises(ValidationError):
        CouponCreate(
            kind="free_shipping",
            discount_percent=10,
            expires_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValidationError):
        CouponCreate(
            kind="percent", discount_percent=100, expires_at=datetime.now(timezone.utc)
        )
    with pytest.raises(ValidationError):
        CouponCreate(kind="free_shipping", max_uses=0)
    assert CouponCreate(kind="free_shipping", max_uses=1).max_uses == 1


def test_percentage_and_free_shipping_discounts():
    async def scenario():
        now = datetime.now(timezone.utc)
        user_id = uuid4()
        coupon = {
            "id": uuid4(),
            "code": "SALE10",
            "kind": "percent",
            "discount_percent": Decimal("10"),
            "active": True,
            "starts_at": now - timedelta(days=1),
            "expires_at": now + timedelta(days=1),
            "assigned_user_id": user_id,
            "max_uses": None,
        }
        db = CouponDatabase(coupon)
        with pytest.raises(APIException) as error:
            await redeem_coupon(db, "SALE10", None, Decimal("200"), Decimal("50"))
        assert error.value.status_code == 403
        _, _, discount = await redeem_coupon(
            db, "sale10", user_id, Decimal("200"), Decimal("50")
        )
        assert discount == Decimal("20.00")
        coupon["kind"] = "free_shipping"
        coupon["discount_percent"] = None
        _, _, discount = await redeem_coupon(
            db, "SALE10", user_id, Decimal("200"), Decimal("50")
        )
        assert discount == Decimal("50")
        coupon["expires_at"] = now - timedelta(seconds=1)
        with pytest.raises(APIException) as error:
            await redeem_coupon(db, "SALE10", user_id, Decimal("200"), Decimal("50"))
        assert error.value.status_code == 409

    asyncio.run(scenario())
