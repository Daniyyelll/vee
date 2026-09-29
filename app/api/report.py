from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_current_user, is_admin
from app.db.session import get_connection
from app.domain.enums import ReportStatus
from app.schemas.report import (
    ReportCreate,
    ReportRead,
    ReportUpdate,
    SalesPeriod,
    SalesReport,
)
from app.schemas.response import APIResponse
from app.services.report import (
    create_report,
    get_report,
    list_reports,
    sales_report,
    update_report,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/sales")
async def show_sales_report(
    period: SalesPeriod = Query(),
    _: dict[str, Any] = Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[SalesReport]:
    report = await sales_report(db, period)
    return APIResponse(status_code=200, message="Sales report", data=report)


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_report(
    request: ReportCreate,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ReportRead]:
    report = await create_report(db, user["id"], request)
    return APIResponse(status_code=201, message="Report submitted", data=report)


@router.get("")
async def show_reports(
    report_status: ReportStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[list[ReportRead]]:
    reports = await list_reports(db, user, report_status, limit, offset)
    return APIResponse(status_code=200, message="Reports", data=reports)


@router.get("/{report_id}")
async def show_report(
    report_id: UUID,
    user: dict[str, Any] = Depends(get_current_user),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ReportRead]:
    report = await get_report(db, user, report_id)
    return APIResponse(status_code=200, message="Report", data=report)


@router.patch("/{report_id}")
async def moderate_report(
    report_id: UUID,
    request: ReportUpdate,
    user: dict[str, Any] = Depends(is_admin),
    db: asyncpg.Connection = Depends(get_connection),
) -> APIResponse[ReportRead]:
    report = await update_report(db, user, report_id, request)
    return APIResponse(status_code=200, message="Report updated", data=report)
