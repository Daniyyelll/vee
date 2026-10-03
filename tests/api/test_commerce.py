from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import order as order_api, report as report_api, review as review_api
from app.api.api import api_router
from app.api.dependencies import get_current_user
from app.core.exceptions import APIException, api_exception_handler
from app.db.session import get_connection
from app.domain.enums import UserRole
from app.schemas.order import OrderRead
from app.schemas.report import ReportRead, SalesReport
from app.schemas.review import ReviewResponse

USER_ID, PRODUCT_ID, REVIEW_ID, REPORT_ID = (uuid4() for _ in range(4))
NOW = datetime.now(timezone.utc)


@pytest.fixture
def commerce_client(monkeypatch):
    app = FastAPI()
    app.include_router(api_router)
    app.add_exception_handler(APIException, api_exception_handler)
    user = {"id": USER_ID, "name": "Buyer", "role": UserRole.CUSTOMER}

    class Connection:
        def __init__(self):
            self.execute = AsyncMock(return_value="INSERT 0 1")

        @asynccontextmanager
        async def transaction(self):
            yield

    connection = Connection()
    app.dependency_overrides[get_connection] = lambda: connection
    app.dependency_overrides[get_current_user] = lambda: user
    order = OrderRead(
        id=uuid4(),
        user={"name": "Buyer", "email": "buyer@example.com", "role": "customer"},
        order_number=1,
        total_price=Decimal("200.00"),
        status="pending",
        shipping_address="Cairo",
        created_at=NOW,
    )
    review = ReviewResponse(
        id=REVIEW_ID,
        rating=5,
        comment="Great",
        username="Buyer",
        created_at=NOW,
        product_id=PRODUCT_ID,
        user_id=USER_ID,
    )
    report = ReportRead(
        id=REPORT_ID,
        user_id=USER_ID,
        product_id=PRODUCT_ID,
        review_id=None,
        target_type="product",
        reason="Incorrect description",
        status="open",
        resolution=None,
        created_at=NOW,
        updated_at=NOW,
    )
    sales = SalesReport(
        start=None,
        end=None,
        total_orders=0,
        delivered_sales=0,
        average_delivered_order_value=0,
        orders_by_status=[],
        top_products=[],
    )
    services = {}
    for module, results in (
        (
            order_api,
            {
                "checkout": order,
                "assign_order_delivery": order,
                "get_order": order,
                "list_orders": [order],
                "update_order_status": order,
            },
        ),
        (
            review_api,
            {
                "create_review": review,
                "list_reviews": [review],
                "update_review": review,
                "delete_review": None,
            },
        ),
        (
            report_api,
            {
                "create_report": report,
                "get_report": report,
                "list_reports": [report],
                "update_report": report,
                "sales_report": sales,
            },
        ),
    ):
        for name, result in results.items():
            services[name] = AsyncMock(return_value=result)
            monkeypatch.setattr(module, name, services[name])
    with TestClient(app) as client:
        yield client, connection, user, services


ROUTES = [
    (
        "POST",
        "/api/orders/checkout",
        {
            "shippingAddress": "Cairo",
            "deliveryArea": "Cairo",
            "name": "Buyer",
            "phone": "01012345678",
        },
        "checkout",
        201,
    ),
    ("GET", "/api/orders", None, "list_orders", 200),
    ("GET", "/api/orders/1", None, "get_order", 200),
    (
        "PATCH",
        "/api/orders/1/delivery-assignment",
        {"deliveryUserId": str(USER_ID)},
        "assign_order_delivery",
        200,
    ),
    (
        "PATCH",
        "/api/orders/1/status",
        {"status": "cancelled"},
        "update_order_status",
        200,
    ),
    ("GET", f"/api/reviews?productId={PRODUCT_ID}", None, "list_reviews", 200),
    (
        "POST",
        "/api/reviews",
        {"productId": str(PRODUCT_ID), "rating": 5, "comment": "Great"},
        "create_review",
        201,
    ),
    (
        "PATCH",
        f"/api/reviews/{REVIEW_ID}",
        {"rating": 4, "comment": "Good"},
        "update_review",
        200,
    ),
    ("DELETE", f"/api/reviews/{REVIEW_ID}", None, "delete_review", 204),
    (
        "POST",
        "/api/reports",
        {"productId": str(PRODUCT_ID), "reason": "Spam"},
        "create_report",
        201,
    ),
    ("GET", "/api/reports", None, "list_reports", 200),
    ("GET", f"/api/reports/{REPORT_ID}", None, "get_report", 200),
    (
        "PATCH",
        f"/api/reports/{REPORT_ID}",
        {"status": "resolved", "resolution": "Fixed"},
        "update_report",
        200,
    ),
    ("GET", "/api/reports/sales", None, "sales_report", 200),
]


@pytest.mark.parametrize("method,path,body,service,expected", ROUTES)
def test_registered_routes_and_authenticated_identity(
    commerce_client, method, path, body, service, expected
):
    client, db, user, services = commerce_client
    user["role"] = UserRole.ADMIN
    response = client.request(method, path, json=body)
    assert response.status_code == expected
    args = services[service].await_args.args
    assert args[0] is db
    if service not in ("sales_report", "list_reviews"):
        assert args[1] in (USER_ID, user)
    if expected == 204:
        assert response.content == b""
    else:
        assert response.json()["status_code"] == expected
    if service == "checkout":
        assert response.json()["data"]["totalPrice"] == "200.00"


@pytest.mark.parametrize(
    "method,path,body,service,expected",
    [row for row in ROUTES if row[3] != "list_reviews"],
)
def test_authentication_required(
    commerce_client, method, path, body, service, expected
):
    client, _, _, services = commerce_client
    del client.app.dependency_overrides[get_current_user]
    assert client.request(method, path, json=body).status_code in (401, 403)
    services[service].assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DELIVERY])
@pytest.mark.parametrize(
    "method,path,body,service",
    [
        ("GET", "/api/reports/sales", None, "sales_report"),
        (
            "PATCH",
            f"/api/reports/{REPORT_ID}",
            {"status": "resolved", "resolution": "Fixed"},
            "update_report",
        ),
    ],
)
def test_admin_report_routes_reject_other_roles(
    commerce_client, role, method, path, body, service
):
    client, _, user, services = commerce_client
    user["role"] = role
    assert client.request(method, path, json=body).status_code == 403
    services[service].assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DELIVERY])
def test_only_admin_can_assign_delivery_staff(commerce_client, role):
    client, _, user, services = commerce_client
    user["role"] = role
    response = client.patch(
        "/api/orders/1/delivery-assignment",
        json={"deliveryUserId": str(USER_ID)},
    )
    assert response.status_code == 403
    services["assign_order_delivery"].assert_not_awaited()


@pytest.mark.parametrize(
    "method,path,body",
    [
        (
            "POST",
            "/api/orders/checkout",
            {
                "shippingAddress": "   ",
                "deliveryArea": "Cairo",
                "name": "Buyer",
                "phone": "01012345678",
            },
        ),
        (
            "POST",
            "/api/orders/checkout",
            {
                "shippingAddress": "Cairo",
                "deliveryArea": "Cairo",
                "name": "Buyer",
                "phone": "01012345678",
                "totalPrice": 1,
            },
        ),
        ("GET", "/api/orders?limit=101", None),
        ("GET", "/api/orders?offset=-1", None),
        ("GET", "/api/orders/0", None),
        ("PATCH", "/api/orders/1/status", {"status": "unknown"}),
        ("PATCH", "/api/orders/1/delivery-assignment", {}),
        (
            "POST",
            "/api/reviews",
            {"productId": str(PRODUCT_ID), "rating": 0, "comment": "Great"},
        ),
        (
            "POST",
            "/api/reviews",
            {"productId": str(PRODUCT_ID), "rating": 5, "comment": "  "},
        ),
        ("POST", "/api/reports", {"reason": "Spam"}),
        (
            "POST",
            "/api/reports",
            {
                "productId": str(PRODUCT_ID),
                "reviewId": str(REVIEW_ID),
                "reason": "Spam",
            },
        ),
        ("POST", "/api/reports", {"productId": "bad", "reason": "Spam"}),
        ("POST", "/api/reports", {"productId": str(PRODUCT_ID), "reason": " "}),
        (
            "GET",
            "/api/reports/sales?start=2026-09-29T00:00:00Z&end=2026-09-28T00:00:00Z",
            None,
        ),
        ("GET", "/api/reports/sales?start=2026-09-29T00:00:00", None),
    ],
)
def test_invalid_requests_never_call_services(commerce_client, method, path, body):
    client, _, user, services = commerce_client
    user["role"] = UserRole.ADMIN
    assert client.request(method, path, json=body).status_code == 422
    for mock in services.values():
        mock.assert_not_awaited()


def test_order_conflict_does_not_send_confirmation(commerce_client):
    client, _, _, services = commerce_client
    services["checkout"].side_effect = APIException("Insufficient stock", 409)
    response = client.post(
        "/api/orders/checkout",
        json={
            "shippingAddress": "Cairo",
            "deliveryArea": "Cairo",
            "name": "Buyer",
            "phone": "01012345678",
        },
    )
    assert response.status_code == 409


def test_public_reviews_do_not_require_authentication(commerce_client):
    client, _, _, services = commerce_client
    del client.app.dependency_overrides[get_current_user]
    response = client.get(f"/api/reviews?productId={PRODUCT_ID}")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == str(REVIEW_ID)
    services["list_reviews"].assert_awaited_once()


@pytest.mark.parametrize("body", [{}, {"rating": None}, {"comment": None}])
def test_empty_or_null_review_updates_are_rejected(commerce_client, body):
    client, _, _, services = commerce_client
    assert client.patch(f"/api/reviews/{REVIEW_ID}", json=body).status_code == 422
    services["update_review"].assert_not_awaited()


def test_sales_period_passed_to_service(commerce_client):
    client, _, user, services = commerce_client
    user["role"] = UserRole.ADMIN
    response = client.get(
        "/api/reports/sales?start=2026-09-01T00:00:00Z&end=2026-10-01T00:00:00Z"
    )
    assert response.status_code == 200
    period = services["sales_report"].await_args.args[1]
    assert period.start.month == 9 and period.end.month == 10
