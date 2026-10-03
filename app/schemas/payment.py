"""Cash-on-delivery request and response models."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.domain.enums import Currency, PaymentMethod, PaymentStatus


class PaymentRead(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )

    id: UUID
    order_id: UUID
    order_number: int
    amount: Decimal
    currency: Currency
    payment_method: PaymentMethod
    payment_status: PaymentStatus
    created_at: datetime
    collected_at: datetime | None = None
    collected_by: UUID | None = None
    refunded_at: datetime | None = None
    refunded_by: UUID | None = None
    refund_reason: str | None = None


class CashRefundRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)
