import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.middleware import RequestSizeLimitMiddleware
from app.core.security import create_access_token, decode_access_token


def test_access_tokens_have_bound_issuer_audience_type_and_id():
    token = create_access_token({"sub": "subject", "ver": 2})
    payload = decode_access_token(token)
    assert payload["typ"] == "access"
    assert payload["jti"]
    assert payload["iss"]
    assert payload["aud"]


def test_request_size_limit_rejects_declared_large_body():
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=8)

    @app.post("/")
    async def accept_body(request: Request):
        return {"size": len(await request.body())}

    with TestClient(app) as client:
        response = client.post("/", content=b"123456789")
    assert response.status_code == 413


def test_production_configuration_fails_closed():
    values = {
        "_env_file": None,
        "environment": "production",
        "BACKEND_URL": "http://api.example.com",
        "FRONTEND_URL": "https://shop.example.com",
        "postgres_host": "db.example.com",
        "postgres_port": 5432,
        "postgres_db": "vee",
        "postgres_user": "vee",
        "postgres_pwd": "database-password",
        "database_sslmode": "disable",
        "secret_jwt_key": "j" * 32,
        "checkout_hmac_key": None,
        "refresh_cookie_secure": False,
        "mail_user": "mailer",
        "mail_pass": "mail-password",
        "mail_host": "smtp.example.com",
        "mail_port": "587",
        "mail_from": "no-reply@example.com",
    }
    with pytest.raises(ValueError):
        Settings(**values)


def test_database_urls_select_the_correct_async_driver():
    values = {
        "_env_file": None,
        "BACKEND_URL": "http://localhost:8084",
        "FRONTEND_URL": "http://localhost:3000",
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_db": "vee",
        "postgres_user": "user@example.com",
        "postgres_pwd": "password/with:specials",
        "database_sslmode": "disable",
        "secret_jwt_key": "j" * 32,
        "mail_user": "mailer",
        "mail_pass": "mail-password",
        "mail_host": "localhost",
        "mail_port": "587",
        "mail_from": "no-reply@example.com",
    }
    configured = Settings(**values)
    assert configured.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert "?ssl=disable" in configured.DATABASE_URL
    assert configured.ASYNCPG_DATABASE_URL.startswith("postgresql://")
    assert "?sslmode=disable" in configured.ASYNCPG_DATABASE_URL
    assert "user%40example.com" in configured.DATABASE_URL
    assert "password%2Fwith%3Aspecials" in configured.DATABASE_URL
