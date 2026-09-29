from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_current_user
from app.db.session import get_connection
from app.schemas.cart import AddToCartRequest, CartRead, UpdateCartItemRequest
from app.schemas.response import APIResponse
from app.services.cart import (
    add_to_cart,
    clear_cart,
    get_cart,
    remove_cart_item,
    update_cart_item,
)

router = APIRouter(prefix="/cart", tags=["cart"])


@router.get("", status_code=status.HTTP_200_OK)
async def show_cart(
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[CartRead]:
    cart = await get_cart(db, user["id"])
    return APIResponse(status_code=200, message="Cart", data=cart)


@router.post("/add", status_code=status.HTTP_200_OK, deprecated=True)
@router.post("/items", status_code=status.HTTP_200_OK)
async def push_to_cart(
    request: AddToCartRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[CartRead]:
    cart = await add_to_cart(db, user["id"], request)
    return APIResponse(status_code=200, message="Cart updated", data=cart)


@router.patch("/items/{product_id}", status_code=status.HTTP_200_OK)
async def change_cart_quantity(
    product_id: UUID,
    request: UpdateCartItemRequest,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[CartRead]:
    cart = await update_cart_item(db, user["id"], product_id, request.quantity)
    return APIResponse(status_code=200, message="Cart updated", data=cart)


@router.delete("/items/{product_id}", status_code=status.HTTP_200_OK)
async def delete_cart_item(
    product_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[CartRead]:
    cart = await remove_cart_item(db, user["id"], product_id)
    return APIResponse(status_code=200, message="Cart item removed", data=cart)


@router.delete("/items", status_code=status.HTTP_200_OK)
async def empty_cart(
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[CartRead]:
    cart = await clear_cart(db, user["id"])
    return APIResponse(status_code=200, message="Cart cleared", data=cart)
