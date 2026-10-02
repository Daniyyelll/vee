from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import status

from app.core.config import settings
from app.core.exceptions import APIException
from app.domain.enums import Currency, OrderStatus, ReportStatus, UserRole
from app.schemas.report import (
    OrderStatusSummary,
    ProductSales,
    ReportCreate,
    ReportRead,
    ReportUpdate,
    SalesPeriod,
    SalesReport,
)

REPORT_COLUMNS = """
    id, user_id, product_id, review_id, target_type, reason, status, resolution,
    created_at, updated_at
"""


async def create_report(
    db: asyncpg.Connection, user_id: UUID, request: ReportCreate
) -> ReportRead:
    try:
        row = await db.fetchrow(
            f"""
            INSERT INTO report (id, user_id, product_id, review_id, target_type, reason)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING {REPORT_COLUMNS}
            """,
            uuid4(),
            user_id,
            request.product_id,
            request.review_id,
            "product" if request.product_id else "review",
            request.reason,
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise APIException(
            "Report target not found.", status.HTTP_404_NOT_FOUND
        ) from exc
    except asyncpg.UniqueViolationError as exc:
        raise APIException(
            "You already have an open report for this target.", status.HTTP_409_CONFLICT
        ) from exc
    return ReportRead.model_validate(dict(row))


async def list_reports(
    db: asyncpg.Connection,
    user: dict[str, Any],
    report_status: ReportStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ReportRead]:
    rows = await db.fetch(
        f"""
        SELECT {REPORT_COLUMNS} FROM report
        WHERE ($1::boolean OR user_id = $2)
          AND ($3::text IS NULL OR status = $3)
        ORDER BY created_at DESC, id DESC LIMIT $4 OFFSET $5
        """,
        user["role"] == UserRole.ADMIN,
        user["id"],
        report_status.value if report_status else None,
        limit,
        offset,
    )
    return [ReportRead.model_validate(dict(row)) for row in rows]


async def get_report(
    db: asyncpg.Connection, user: dict[str, Any], report_id: UUID
) -> ReportRead:
    row = await db.fetchrow(
        f"""
        SELECT {REPORT_COLUMNS} FROM report
        WHERE id = $1 AND ($2::boolean OR user_id = $3)
        """,
        report_id,
        user["role"] == UserRole.ADMIN,
        user["id"],
    )
    if row is None:
        raise APIException("Report not found.", status.HTTP_404_NOT_FOUND)
    return ReportRead.model_validate(dict(row))


async def update_report(
    db: asyncpg.Connection, user: dict[str, Any], report_id: UUID, request: ReportUpdate
) -> ReportRead:
    if user["role"] != UserRole.ADMIN:
        raise APIException("Administrator access required.", status.HTTP_403_FORBIDDEN)
    if request.status == ReportStatus.OPEN:
        raise APIException(
            "Choose resolved or dismissed.", status.HTTP_422_UNPROCESSABLE_CONTENT
        )
    row = await db.fetchrow(
        f"""
        UPDATE report SET status = $2, resolution = $3, updated_at = NOW()
        WHERE id = $1 AND status = 'open' RETURNING {REPORT_COLUMNS}
        """,
        report_id,
        request.status.value,
        request.resolution,
    )
    if row is None:
        existing = await get_report(db, user, report_id)
        if (
            existing.status == request.status
            and existing.resolution == request.resolution
        ):
            return existing
        raise APIException("Report is already closed.", status.HTTP_409_CONFLICT)
    return ReportRead.model_validate(dict(row))


async def sales_report(db: asyncpg.Connection, period: SalesPeriod) -> SalesReport:
    # All sections describe the same snapshot even if orders change mid-request.
    async with db.transaction(isolation="repeatable_read", readonly=True):
        currencies = await db.fetch(
            """
            SELECT DISTINCT currency::text AS currency FROM "order"
            WHERE ($1::timestamptz IS NULL OR created_at >= $1)
              AND ($2::timestamptz IS NULL OR created_at < $2)
            """,
            period.start,
            period.end,
        )
        if len(currencies) > 1 and period.currency is None:
            raise APIException(
                "Choose a currency for this report.", status.HTTP_409_CONFLICT
            )
        currency = period.currency or (
            Currency(currencies[0]["currency"])
            if currencies
            else settings.payment_currency
        )
        rows = await db.fetch(
            """
            SELECT status::text AS status, count(*) AS count,
                   COALESCE(sum(total_price), 0) AS order_value
            FROM "order"
            WHERE ($1::timestamptz IS NULL OR created_at >= $1)
              AND ($2::timestamptz IS NULL OR created_at < $2)
              AND currency::text = $3
            GROUP BY status ORDER BY status::text
            """,
            period.start,
            period.end,
            currency.value,
        )
        refunded = await db.fetchval(
            """
            SELECT COALESCE(sum(p.amount), 0) FROM payment p
            JOIN "order" o ON o.id = p.order_id
            WHERE o.status = 'DELIVERED'
              AND p.payment_status = 'REFUNDED'
              AND ($1::timestamptz IS NULL OR o.created_at >= $1)
              AND ($2::timestamptz IS NULL OR o.created_at < $2)
              AND o.currency::text = $3
            """,
            period.start,
            period.end,
            currency.value,
        )
        products = await db.fetch(
            """
            SELECT oi.product_id, max(oi.product_name) AS product_name,
                   sum(oi.quantity) AS quantity,
                   sum(oi.quantity * oi.unit_price) AS sales
            FROM order_item oi JOIN "order" o ON o.id = oi.order_id
            LEFT JOIN payment p ON p.order_id = o.id
                AND p.payment_status = 'REFUNDED'
            WHERE o.status = 'DELIVERED'
              AND p.id IS NULL
              AND ($1::timestamptz IS NULL OR o.created_at >= $1)
              AND ($2::timestamptz IS NULL OR o.created_at < $2)
              AND o.currency::text = $3
            GROUP BY oi.product_id ORDER BY sales DESC, oi.product_id LIMIT 10
            """,
            period.start,
            period.end,
            currency.value,
        )
    indexed = {OrderStatus(row["status"].lower()): row for row in rows}
    summaries = [
        OrderStatusSummary(
            status=value,
            count=indexed[value]["count"] if value in indexed else 0,
            order_value=indexed[value]["order_value"] if value in indexed else 0,
        )
        for value in OrderStatus
    ]
    delivered = next(row for row in summaries if row.status == OrderStatus.DELIVERED)
    return SalesReport(
        start=period.start,
        end=period.end,
        total_orders=sum(row.count for row in summaries),
        delivered_sales=delivered.order_value,
        refunded_amount=refunded,
        net_sales=delivered.order_value - refunded,
        currency=currency,
        average_delivered_order_value=(
            (delivered.order_value / delivered.count).quantize(Decimal("0.01"))
            if delivered.count
            else 0
        ),
        orders_by_status=summaries,
        top_products=[ProductSales.model_validate(dict(row)) for row in products],
    )
