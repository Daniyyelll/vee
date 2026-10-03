import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
from pydantic import ValidationError

from app.core.exceptions import APIException
from app.schemas.product import ProductUpdate
from app.services.product import update_product


def test_product_update_accepts_category_reassignment_and_rejects_null():
    category_id = uuid4()
    assert ProductUpdate(category_id=category_id).category_id == category_id
    with pytest.raises(ValidationError):
        ProductUpdate(category_id=None)


def test_product_update_changes_category_and_returns_it():
    product_id = uuid4()
    category_id = uuid4()
    db = AsyncMock()
    db.fetchval.return_value = product_id
    db.fetchrow.return_value = {
        "id": product_id,
        "product_slug": "lip-balm",
        "category_id": category_id,
        "currency": "EGP",
        "product_name": "Lip Balm",
        "description": None,
        "price": Decimal("170.00"),
        "stock_quantity": 12,
        "image_url": None,
        "active": True,
    }

    result = asyncio.run(
        update_product(db, "lip-balm", ProductUpdate(category_id=category_id))
    )

    assert result.category_id == category_id
    query, new_category_id, updated_product_id = db.fetchrow.call_args.args
    assert "category_id = $1" in query
    assert new_category_id == category_id
    assert updated_product_id == product_id


def test_product_update_rejects_deleted_category():
    db = AsyncMock()
    db.fetchval.return_value = uuid4()
    db.fetchrow.side_effect = asyncpg.ForeignKeyViolationError("missing category")

    with pytest.raises(APIException) as error:
        asyncio.run(update_product(db, "lip-balm", ProductUpdate(category_id=uuid4())))

    assert error.value.status_code == 422
