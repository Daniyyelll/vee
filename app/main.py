import asyncio
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.api.api import api_router as api_router
from app.core.config import settings
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import connect_database, disconnect_database, get_pool
from app.services.outbox import maintenance_worker
from app.services.rate_limit import consume_rate_limit


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to database")

    settings.product_upload_dir.mkdir(parents=True, exist_ok=True)

    await connect_database()
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("SELECT 1")

    worker = asyncio.create_task(maintenance_worker(pool))
    app.state.maintenance_worker = worker
    try:
        yield
    finally:
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        await disconnect_database()


app = FastAPI(title="Vee E-Commerce API", version="0.1.0", lifespan=lifespan)
logger = logging.getLogger("uvicorn.error")
app.mount(
    "/uploads/products",
    StaticFiles(directory=settings.product_upload_dir, check_dir=False),
    name="product-images",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL.rstrip("/")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(APIException, api_exception_handler)

PUBLIC_LIMITS = {
    "/api/auth/login": (30, 900),
    "/api/auth/refresh": (120, 60),
    "/api/auth/register": (10, 3600),
    "/api/auth/forgot-password": (10, 3600),
    "/api/auth/reset-password": (20, 900),
    "/api/orders/guest-checkout": (10, 3600),
}


@app.middleware("http")
async def limit_public_requests(request: Request, call_next):
    rule = PUBLIC_LIMITS.get(request.url.path) if request.method == "POST" else None
    if rule is not None:
        async with get_pool().acquire() as db:
            try:
                await consume_rate_limit(
                    db,
                    request.url.path,
                    request.client.host if request.client else "unknown",
                    limit=rule[0],
                    window_seconds=rule[1],
                )
            except APIException as exc:
                return await api_exception_handler(request, exc)
    return await call_next(request)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_id = uuid4().hex
    request.state.request_id = request_id
    started = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        (time.monotonic() - started) * 1000,
    )
    return response


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled application error request_id=%s",
        getattr(request.state, "request_id", "unknown"),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "status_code": 500,
            "message": "An unexpected server error occurred.",
        },
        headers={"X-Request-ID": getattr(request.state, "request_id", "unknown")},
    )


app.include_router(api_router)
