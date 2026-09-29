from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from app.domain.enums import OrderStatus

from .payment import PaymentRead
from .user import UserRead


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    shipping_address: str = Field(min_length=1, max_length=1000)


class UpdateOrderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OrderStatus


class OrderItemRead(BaseModel):
    id: UUID
    product_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    is_reviewed: bool

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )

    @computed_field
    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price


class OrderRead(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )

    id: UUID
    user: UserRead
    order_number: int
    total_price: Decimal
    status: OrderStatus
    shipping_address: str
    created_at: datetime
    items: list[OrderItemRead] = Field(default_factory=list)

    payment: PaymentRead | None = None
