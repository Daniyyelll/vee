from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import payment as payment_api
from app.api.api import api_router
from app.api.dependencies import get_current_user
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import get_connection
from app.domain.enums import UserRole
from app.schemas.payment import PaymentRead

USER_ID = uuid4()


@pytest.fixture
def payment_client(monkeypatch):
    app = FastAPI()
    app.include_router(api_router)
    app.add_exception_handler(APIException, api_exception_handler)
    db = object()
    user = {"id": USER_ID, "role": UserRole.ADMIN}
    app.dependency_overrides[get_connection] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    payment = PaymentRead(
        id=uuid4(),
        order_id=uuid4(),
        order_number=1,
        amount=Decimal("400.00"),
        currency="EGP",
        payment_method="Cash",
        payment_status="pending",
        created_at=datetime.now(timezone.utc),
    )
    services = {}
    for name in ("get_payment", "create_cash_payment", "collect_cash", "refund_cash"):
        services[name] = AsyncMock(return_value=payment)
        monkeypatch.setattr(payment_api, name, services[name])
    with TestClient(app) as client:
        yield client, db, user, services


ROUTES = [
    ("GET", "/api/payments/1", None, "get_payment"),
    ("POST", "/api/payments/1", None, "create_cash_payment"),
    ("POST", "/api/payments/1/collect", None, "collect_cash"),
    ("POST", "/api/payments/1/refund", {"reason": "Cash returned"}, "refund_cash"),
]


@pytest.mark.parametrize("method,path,body,service", ROUTES)
def test_payment_routes_pass_staff_identity_and_serialize_cash(
    payment_client, method, path, body, service
):
    client, db, user, services = payment_client
    response = client.request(method, path, json=body)
    assert response.status_code == 200
    assert response.json()["data"]["amount"] == "400.00"
    assert response.json()["data"]["currency"] == "EGP"
    assert response.json()["data"]["paymentMethod"] == "Cash"
    assert services[service].await_args.args[:3] == (db, user, 1)


@pytest.mark.parametrize("method,path,body,service", ROUTES)
def test_payment_routes_require_authentication(
    payment_client, method, path, body, service
):
    client, _, _, services = payment_client
    del client.app.dependency_overrides[get_current_user]
    assert client.request(method, path, json=body).status_code in (401, 403)
    services[service].assert_not_awaited()


@pytest.mark.parametrize("method,path,body,service", ROUTES[1:])
def test_customers_cannot_modify_payment_status(
    payment_client, method, path, body, service
):
    client, _, user, services = payment_client
    user["role"] = UserRole.CUSTOMER
    assert client.request(method, path, json=body).status_code == 403
    services[service].assert_not_awaited()


def test_delivery_cannot_refund(payment_client):
    client, _, user, services = payment_client
    user["role"] = UserRole.DELIVERY
    assert (
        client.post("/api/payments/1/refund", json={"reason": "Returned"}).status_code
        == 403
    )
    services["refund_cash"].assert_not_awaited()


@pytest.mark.parametrize(
    "body", [{}, {"reason": " "}, {"reason": "Returned", "amount": 1}]
)
def test_refund_requires_reason_and_rejects_amount_override(payment_client, body):
    client, _, _, services = payment_client
    assert client.post("/api/payments/1/refund", json=body).status_code == 422
    services["refund_cash"].assert_not_awaited()


@pytest.mark.parametrize("status_code", [404, 409])
def test_payment_errors_keep_status(payment_client, status_code):
    client, _, _, services = payment_client
    services["collect_cash"].side_effect = APIException("Cannot collect", status_code)
    assert client.post("/api/payments/1/collect").status_code == status_code


def test_order_number_validation(payment_client):
    client, _, _, services = payment_client
    assert client.get("/api/payments/0").status_code == 422
    services["get_payment"].assert_not_awaited()
