from typing import Any

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, status

from app.api.dependencies import get_current_user
from app.db.session import get_connection
from app.domain.enums import OrderStatus
from app.schemas.order import CheckoutRequest, OrderRead, UpdateOrderStatus
from app.schemas.response import APIResponse
from app.services.email import (
    send_order_confirmation_email,
    send_order_status_update_email,
)
from app.services.order import checkout, get_order, list_orders, update_order_status

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def place_order(
    request: CheckoutRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderRead]:
    order = await checkout(db, user, request)
    background_tasks.add_task(
        send_order_confirmation_email, str(order.user.email), order.user.name, order
    )
    return APIResponse(status_code=201, message="Order placed", data=order)


@router.get("")
async def show_orders(
    order_status: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[OrderRead]]:
    orders = await list_orders(db, user, order_status, limit, offset)
    return APIResponse(status_code=200, message="Orders", data=orders)


@router.get("/{order_number}")
async def show_order(
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderRead]:
    order = await get_order(db, user, order_number)
    return APIResponse(status_code=200, message="Order", data=order)


@router.patch("/{order_number}/status")
async def change_order_status(
    request: UpdateOrderStatus,
    background_tasks: BackgroundTasks,
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderRead]:
    order = await update_order_status(db, user, order_number, request.status)
    background_tasks.add_task(
        send_order_status_update_email, str(order.user.email), order.user.name, order
    )
    return APIResponse(status_code=200, message="Order status updated", data=order)
