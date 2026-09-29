from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Path

from app.api.dependencies import get_current_user, is_admin, is_delivery_or_admin
from app.db.session import get_connection
from app.schemas.payment import CashRefundRequest, PaymentRead
from app.schemas.response import APIResponse
from app.services.payment import (
    collect_cash,
    create_cash_payment,
    get_payment,
    refund_cash,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/{order_number}")
async def show_payment(
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[PaymentRead]:
    payment = await get_payment(db, user, order_number)
    return APIResponse(status_code=200, message="Payment", data=payment)


@router.post("/{order_number}")
async def initialize_legacy_payment(
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(is_delivery_or_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[PaymentRead]:
    payment = await create_cash_payment(db, user, order_number)
    return APIResponse(
        status_code=200, message="Cash payment initialized", data=payment
    )


@router.post("/{order_number}/collect")
async def record_cash_collection(
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(is_delivery_or_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[PaymentRead]:
    payment = await collect_cash(db, user, order_number)
    return APIResponse(
        status_code=200, message="Cash collection recorded", data=payment
    )


@router.post("/{order_number}/refund")
async def record_cash_refund(
    request: CashRefundRequest,
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[PaymentRead]:
    payment = await refund_cash(db, user, order_number, request)
    return APIResponse(status_code=200, message="Cash refund recorded", data=payment)
