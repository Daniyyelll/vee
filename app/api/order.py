from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from app.api.dependencies import get_current_user, is_admin
from app.db.session import get_connection
from app.domain.enums import OrderStatus
from app.schemas.order import (
    AssignOrderDelivery,
    CartQuoteRequest,
    CheckoutRequest,
    GuestCheckoutRequest,
    GuestQuoteRequest,
    OrderQuote,
    OrderRead,
    OrderReceiptRead,
    PlacedOrderRead,
    UpdateOrderStatus,
)
from app.schemas.response import APIResponse
from app.services.order import (
    assign_order_delivery,
    checkout,
    get_order,
    get_order_receipt,
    guest_checkout,
    list_orders,
    order_receipt_token,
    quote_cart_order,
    quote_guest_order,
    update_order_status,
)
from app.services.rate_limit import consume_rate_limit

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/quote")
async def quote_guest(
    body: GuestQuoteRequest,
    request: Request,
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderQuote]:
    await consume_rate_limit(
        db,
        "guest-quote",
        request.client.host if request.client else "unknown",
        limit=60,
        window_seconds=60,
    )
    quote = await quote_guest_order(db, body.items, body.coupon_code)
    return APIResponse(status_code=200, message="Order quote", data=quote)


@router.post("/cart-quote")
async def quote_cart(
    body: CartQuoteRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderQuote]:
    quote = await quote_cart_order(db, user["id"], body.coupon_code)
    return APIResponse(status_code=200, message="Order quote", data=quote)


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
async def place_order(
    request: CheckoutRequest,
    response: Response,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[PlacedOrderRead]:
    order = await checkout(db, user, request)
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(
        status_code=201,
        message="Order placed",
        data=PlacedOrderRead(
            **order.model_dump(), receipt_token=order_receipt_token(order.id)
        ),
    )


@router.post("/guest-checkout", status_code=status.HTTP_201_CREATED)
async def place_guest_order(
    request: GuestCheckoutRequest,
    response: Response,
    idempotency_key: str = Header(min_length=8, max_length=128),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[PlacedOrderRead]:
    order = await guest_checkout(db, request, idempotency_key)
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(
        status_code=201,
        message="Order placed",
        data=PlacedOrderRead(
            **order.model_dump(), receipt_token=order_receipt_token(order.id)
        ),
    )


@router.get("/receipt/{order_number}")
async def show_receipt(
    request: Request,
    response: Response,
    order_number: int = Path(gt=0),
    receipt_token: str = Header(min_length=64, max_length=64),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderReceiptRead]:
    await consume_rate_limit(
        db,
        "order-receipt",
        request.client.host if request.client else "unknown",
        limit=30,
        window_seconds=60,
    )
    receipt = await get_order_receipt(db, order_number, receipt_token)
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(status_code=200, message="Order receipt", data=receipt)


@router.get("")
async def show_orders(
    order_status: OrderStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[OrderRead]]:
    orders = await list_orders(db, user, order_status, limit, offset)
    return APIResponse(status_code=200, message="Orders", data=orders)


@router.get("/mine")
async def show_my_orders(
    response: Response,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[OrderRead]]:
    orders = await list_orders(db, user, limit=limit, offset=offset, mine_only=True)
    response.headers["Cache-Control"] = "no-store"
    return APIResponse(status_code=200, message="Your orders", data=orders)


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
    order_number: int = Path(gt=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderRead]:
    order = await update_order_status(db, user, order_number, request.status)
    return APIResponse(status_code=200, message="Order status updated", data=order)


@router.patch("/{order_number}/delivery-assignment")
async def change_delivery_assignment(
    request: AssignOrderDelivery,
    order_number: int = Path(gt=0),
    admin: dict[str, Any] = Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[OrderRead]:
    order = await assign_order_delivery(
        db, admin, order_number, request.delivery_user_id
    )
    return APIResponse(
        status_code=200,
        message="Delivery assignment updated",
        data=order,
    )
