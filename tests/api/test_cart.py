from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import cart as cart_api
from app.api.api import api_router
from app.api.dependencies import get_current_user
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import get_connection
from app.schemas.cart import CartItemRead, CartRead

USER_ID = uuid4()
PRODUCT_ID = uuid4()


@pytest.fixture
def cart_client(monkeypatch):
    app = FastAPI()
    app.include_router(api_router)
    app.add_exception_handler(APIException, api_exception_handler)
    connection = object()
    app.dependency_overrides[get_connection] = lambda: connection
    app.dependency_overrides[get_current_user] = lambda: {"id": USER_ID}
    result = CartRead(
        user_id=USER_ID,
        items=[
            CartItemRead(
                product_id=PRODUCT_ID,
                product_name="T-shirt",
                product_price=Decimal("200.00"),
                quantity=2,
                subtotal=Decimal("400.00"),
            )
        ],
        total_quantity=2,
        total_price=Decimal("400.00"),
    )
    services = {}
    for name in (
        "get_cart",
        "add_to_cart",
        "update_cart_item",
        "remove_cart_item",
        "clear_cart",
    ):
        services[name] = AsyncMock(return_value=result)
        monkeypatch.setattr(cart_api, name, services[name])

    with TestClient(app) as client:
        yield client, connection, services


@pytest.mark.parametrize(
    ("method", "path", "body", "service"),
    [
        ("GET", "/api/cart", None, "get_cart"),
        (
            "POST",
            "/api/cart/items",
            {"product_id": str(PRODUCT_ID), "quantity": 2},
            "add_to_cart",
        ),
        (
            "POST",
            "/api/cart/add",
            {"product_id": str(PRODUCT_ID)},
            "add_to_cart",
        ),
        (
            "PATCH",
            f"/api/cart/items/{PRODUCT_ID}",
            {"quantity": 2},
            "update_cart_item",
        ),
        (
            "DELETE",
            f"/api/cart/items/{PRODUCT_ID}",
            None,
            "remove_cart_item",
        ),
        ("DELETE", "/api/cart/items", None, "clear_cart"),
    ],
)
def test_registered_endpoints_use_authenticated_owner(
    cart_client, method, path, body, service
):
    client, connection, services = cart_client
    response = client.request(method, path, json=body)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["userId"] == str(USER_ID)
    assert data["totalQuantity"] == 2
    assert data["totalPrice"] == "400.00"
    assert data["items"][0]["productId"] == str(PRODUCT_ID)
    args = services[service].await_args.args
    assert args[:2] == (connection, USER_ID)
    if service == "add_to_cart":
        assert args[2].product_id == PRODUCT_ID
        assert args[2].quantity == body.get("quantity", 1)
    elif service == "update_cart_item":
        assert args[2:] == (PRODUCT_ID, 2)
    elif service == "remove_cart_item":
        assert args[2:] == (PRODUCT_ID,)
    services[service].assert_awaited_once()
    for name, mock in services.items():
        if name != service:
            mock.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/cart", None),
        ("POST", "/api/cart/items", {"product_id": str(PRODUCT_ID)}),
        ("POST", "/api/cart/add", {"product_id": str(PRODUCT_ID)}),
        ("PATCH", f"/api/cart/items/{PRODUCT_ID}", {"quantity": 1}),
        ("DELETE", f"/api/cart/items/{PRODUCT_ID}", None),
        ("DELETE", "/api/cart/items", None),
    ],
)
def test_cart_endpoints_require_authentication(cart_client, method, path, body):
    client, _, services = cart_client
    del client.app.dependency_overrides[get_current_user]

    response = client.request(method, path, json=body)

    assert response.status_code in (401, 403)
    for mock in services.values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("quantity", [0, -1])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_nonpositive_quantities_are_rejected(cart_client, method, quantity):
    client, _, services = cart_client
    path = "/api/cart/items"
    body = {"quantity": quantity}
    if method == "POST":
        body["product_id"] = str(PRODUCT_ID)
    else:
        path += f"/{PRODUCT_ID}"

    assert client.request(method, path, json=body).status_code == 422
    for mock in services.values():
        mock.assert_not_awaited()


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_invalid_product_uuid_is_rejected(cart_client, method):
    client, _, services = cart_client
    response = client.request(
        method, "/api/cart/items/not-a-uuid", json={"quantity": 1}
    )
    assert response.status_code == 422
    for mock in services.values():
        mock.assert_not_awaited()


def test_update_requires_quantity(cart_client):
    client, _, services = cart_client
    response = client.patch(f"/api/cart/items/{PRODUCT_ID}", json={})
    assert response.status_code == 422
    services["update_cart_item"].assert_not_awaited()


@pytest.mark.parametrize("status_code", [404, 409])
def test_service_errors_preserve_their_status(cart_client, status_code):
    client, _, services = cart_client
    services["add_to_cart"].side_effect = APIException(
        "Product unavailable", status_code
    )

    response = client.post("/api/cart/items", json={"product_id": str(PRODUCT_ID)})

    assert response.status_code == status_code
    assert response.json()["message"] == "Product unavailable"
