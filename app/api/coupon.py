import asyncpg
from fastapi import APIRouter, Depends, status

from app.api.dependencies import is_admin
from app.db.session import get_connection
from app.schemas.coupon import CouponCreate, CouponRead
from app.schemas.response import APIResponse
from app.services.audit import record_audit
from app.services.coupon import create_coupon, list_coupons

router = APIRouter(prefix="/coupons", tags=["coupons"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_coupon(
    request: CouponCreate,
    admin=Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[CouponRead]:
    async with db.transaction():
        coupon = await create_coupon(db, request)
        await record_audit(db, admin, "coupon.created", "coupon", coupon.id)
    return APIResponse(status_code=201, message="Coupon created", data=coupon)


@router.get("")
async def show_coupons(
    _admin=Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[CouponRead]]:
    return APIResponse(status_code=200, message="Coupons", data=await list_coupons(db))
