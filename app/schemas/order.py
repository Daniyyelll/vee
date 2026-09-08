from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from app.models.order import OrderStatus

from .user import UserRead


class CheckoutRequest(BaseModel):
    shipping_address: str


class UpdateOrderStatus(BaseModel):
    status: OrderStatus


class OrderItemRead(BaseModel):
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

    user: UserRead
    order_number: int
    total_price: Decimal
    status: OrderStatus
    shipping_address: str
    created_at: datetime
    items: list[OrderItemRead] = Field(default_factory=list)
