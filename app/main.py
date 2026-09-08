from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.api import router as api_router

from app.core.config import settings
from app.db.session import get_session, engine
from sqlmodel import text

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Attempting to connect to database")

    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    print("Successfully connected to database")

    yield

    print("Shutting down application")

app = FastAPI(title="Vee E-Commerce API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
