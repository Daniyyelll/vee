from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import auth as auth_api
from app.core.config import settings
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import get_connection
from app.schemas.user import TokenData


def test_login_refresh_and_logout_manage_http_only_cookie(monkeypatch):
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.add_exception_handler(APIException, api_exception_handler)
    db = AsyncMock()

    @asynccontextmanager
    async def transaction():
        yield

    db.transaction = transaction
    db.fetchval.return_value = 2
    app.dependency_overrides[get_connection] = lambda: db
    user = {
        "id": uuid4(),
        "name": "Buyer",
        "email": "buyer@example.com",
        "role": "customer",
        "active": True,
    }
    monkeypatch.setattr(
        auth_api,
        "login_user",
        AsyncMock(return_value=TokenData(token="access-1", user=user)),
    )
    expires_at = datetime.now(timezone.utc) + timedelta(days=14)
    create = AsyncMock(return_value=("refresh-1", expires_at))
    rotate = AsyncMock(return_value=("refresh-2", expires_at, "access-2", user))
    revoke = AsyncMock()
    monkeypatch.setattr(auth_api, "create_refresh_session", create)
    monkeypatch.setattr(auth_api, "rotate_refresh_session", rotate)
    monkeypatch.setattr(auth_api, "revoke_refresh_session", revoke)

    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": user["email"], "password": "example-password"},
            headers={"Origin": settings.FRONTEND_URL.rstrip("/")},
        )
        assert login.status_code == 200
        assert login.json()["data"]["token"] == "access-1"
        assert client.cookies.get(auth_api.REFRESH_COOKIE) == "refresh-1"
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "path=/api/auth" in login.headers["set-cookie"].lower()
        assert "samesite=lax" in login.headers["set-cookie"].lower()
        assert ("secure" in login.headers["set-cookie"].lower()) == (
            settings.REFRESH_COOKIE_SECURE
        )
        assert login.headers["cache-control"] == "no-store"
        create.assert_awaited_once_with(db, user["id"], 2)

        refreshed = client.post(
            "/api/auth/refresh", headers={"Origin": settings.FRONTEND_URL.rstrip("/")}
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["data"]["token"] == "access-2"
        rotate.assert_awaited_once_with(db, "refresh-1")
        assert client.cookies.get(auth_api.REFRESH_COOKIE) == "refresh-2"

        logged_out = client.post(
            "/api/auth/logout", headers={"Origin": settings.FRONTEND_URL.rstrip("/")}
        )
        assert logged_out.status_code == 204
        assert logged_out.content == b""
        revoke.assert_awaited_once_with(db, "refresh-2")
        assert client.cookies.get(auth_api.REFRESH_COOKIE) is None
        assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_rejects_untrusted_browser_origin(monkeypatch):
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    app.add_exception_handler(APIException, api_exception_handler)
    db = AsyncMock()
    app.dependency_overrides[get_connection] = lambda: db
    rotate = AsyncMock()
    monkeypatch.setattr(auth_api, "rotate_refresh_session", rotate)

    with TestClient(app) as client:
        client.cookies.set(auth_api.REFRESH_COOKIE, "refresh-1")
        response = client.post(
            "/api/auth/refresh", headers={"Origin": "https://other.example"}
        )
    assert response.status_code == 403
    rotate.assert_not_awaited()
