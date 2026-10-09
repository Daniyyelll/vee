from fastapi import APIRouter, HTTPException, Request

from app.api.auth import router as auth_router
from app.api.cart import router as cart_router
from app.api.category import router as category_router
from app.api.coupon import router as coupon_router
from app.api.landing_image import router as landing_image_router
from app.api.order import router as order_router
from app.api.payment import router as payment_router
from app.api.product import router as product_router
from app.api.report import router as report_router
from app.api.review import router as review_router
from app.api.user import router as user_router
from app.db.session import get_pool

api_router = APIRouter(prefix="/api", tags=["api"])


@api_router.get("/health")
async def health():
    return {"status": "ok"}


@api_router.get("/ready")
async def ready(request: Request):
    worker = getattr(request.app.state, "maintenance_worker", None)
    if worker is not None and worker.done():
        raise HTTPException(status_code=503, detail="Maintenance worker unavailable")
    try:
        async with get_pool().acquire() as db:
            await db.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready"}


api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(user_router, tags=["user"])
api_router.include_router(category_router, tags=["category"])
api_router.include_router(product_router, tags=["product"])
api_router.include_router(landing_image_router)
api_router.include_router(cart_router)
api_router.include_router(order_router)
api_router.include_router(review_router)
api_router.include_router(report_router)

api_router.include_router(payment_router)
api_router.include_router(coupon_router)
