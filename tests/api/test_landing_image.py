"""Access control and atomic publishing for landing image administration."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import landing_image as landing_api
from app.api.dependencies import get_current_user
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import get_connection


class FakeDb:
    @asynccontextmanager
    async def transaction(self):
        yield


def make_app(user):
    app = FastAPI()
    app.include_router(landing_api.router, prefix="/api")
    app.add_exception_handler(APIException, api_exception_handler)
    app.dependency_overrides[get_connection] = lambda: FakeDb()
    app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_customer_cannot_publish_landing_image(monkeypatch):
    prepare = AsyncMock()
    monkeypatch.setattr(landing_api, "prepare_image", prepare)
    app = make_app({"id": uuid4(), "role": "customer"})
    response = TestClient(app).patch(
        "/api/landing-images/hero",
        data={"altText": "A description", "caption": ""},
    )
    assert response.status_code == 403
    prepare.assert_not_awaited()


def test_failed_database_write_discards_new_upload(monkeypatch):
    prepare = AsyncMock(
        return_value=("https://test/large.webp", "https://test/small.webp")
    )
    update = AsyncMock(side_effect=RuntimeError("database unavailable"))
    discard = AsyncMock()
    monkeypatch.setattr(landing_api, "prepare_image", prepare)
    monkeypatch.setattr(landing_api, "update_landing_image", update)
    monkeypatch.setattr(landing_api, "discard_image", discard)
    app = make_app({"id": uuid4(), "role": "admin"})
    client = TestClient(app, raise_server_exceptions=False)
    response = client.patch(
        "/api/landing-images/hero",
        data={"altText": "A description", "caption": ""},
        files={"imageFile": ("photo.png", b"image", "image/png")},
    )
    assert response.status_code == 500
    update.assert_awaited_once()
    discard.assert_awaited_once_with(prepare.return_value)


def test_public_read_is_not_cached(monkeypatch):
    images = [{"slot": "hero", "imageUrl": "/images/vee-atelier.webp"}]
    monkeypatch.setattr(
        landing_api, "list_landing_images", AsyncMock(return_value=images)
    )
    app = FastAPI()
    app.include_router(landing_api.router, prefix="/api")
    app.dependency_overrides[get_connection] = lambda: FakeDb()
    response = TestClient(app).get("/api/landing-images")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"] == images
