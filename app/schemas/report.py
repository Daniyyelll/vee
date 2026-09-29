from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from app.domain.enums import OrderStatus, ReportStatus


class ReportModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


class ReportCreate(ReportModel):
    product_id: UUID | None = None
    review_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def one_target(self):
        if (self.product_id is None) == (self.review_id is None):
            raise ValueError("Provide exactly one of productId or reviewId")
        return self


class ReportUpdate(ReportModel):
    status: ReportStatus
    resolution: str = Field(min_length=1, max_length=2000)


class ReportRead(ReportModel):
    id: UUID
    user_id: UUID
    product_id: UUID | None
    review_id: UUID | None
    target_type: str
    reason: str
    status: ReportStatus
    resolution: str | None
    created_at: datetime
    updated_at: datetime


class SalesPeriod(ReportModel):
    start: AwareDatetime | None = None
    end: AwareDatetime | None = None

    @model_validator(mode="after")
    def chronological(self):
        if self.start is not None and self.end is not None and self.start >= self.end:
            raise ValueError("start must precede end")
        return self


class OrderStatusSummary(ReportModel):
    status: OrderStatus
    count: int
    order_value: Decimal


class ProductSales(ReportModel):
    product_id: UUID
    product_name: str
    quantity: int
    sales: Decimal


class SalesReport(ReportModel):
    start: datetime | None
    end: datetime | None
    total_orders: int
    delivered_sales: Decimal
    average_delivered_order_value: Decimal
    orders_by_status: list[OrderStatusSummary]
    top_products: list[ProductSales]
