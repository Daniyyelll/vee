import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

from app.api.api import api_router as api_router
from app.core.config import settings
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import connect_database, disconnect_database, get_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Attempting to connect to database")

    await connect_database()
    pool = get_pool()
    async with pool.acquire() as connection:
        await connection.execute("SELECT 1")

    print("Successfully connected to database")

    yield

    await disconnect_database()
    print("Shutting down application")


app = FastAPI(title="Vee E-Commerce API", version="0.1.0", lifespan=lifespan)
logger = logging.getLogger(__name__)
app.mount(
    "/uploads/products",
    StaticFiles(directory=settings.product_upload_dir, check_dir=False),
    name="product-images",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(APIException, api_exception_handler)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"status": 500, "message": "An unexpected server error occurred."},
    )


app.include_router(api_router)
