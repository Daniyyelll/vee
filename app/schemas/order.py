from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field
from pydantic.alias_generators import to_camel

from app.domain.enums import Currency, DeliveryArea, OrderStatus

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
    delivery_area: DeliveryArea
    name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=5, max_length=40)
    coupon_code: str | None = Field(default=None, min_length=1, max_length=64)
    expected_total: Decimal | None = Field(default=None, ge=0)


class GuestCheckoutItem(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid"
    )

    product_id: UUID
    quantity: int = Field(gt=0, le=100)


class GuestCheckoutRequest(CheckoutRequest):
    email: EmailStr
    items: list[GuestCheckoutItem] = Field(min_length=1, max_length=100)


class GuestQuoteRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        extra="forbid",
    )

    items: list[GuestCheckoutItem] = Field(min_length=1, max_length=100)
    coupon_code: str | None = Field(default=None, min_length=1, max_length=64)


class CartQuoteRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    coupon_code: str | None = Field(default=None, min_length=1, max_length=64)


class QuoteItemRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    product_id: UUID
    product_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class OrderQuote(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    items: list[QuoteItemRead]
    subtotal_price: Decimal
    shipping_fee: Decimal
    discount_amount: Decimal
    total_price: Decimal
    coupon_code: str | None
    currency: Currency


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
    user: UserRead | None = None
    guest_name: str | None = None
    guest_email: EmailStr | None = None
    guest_phone: str | None = None
    recipient_name: str | None = None
    recipient_phone: str | None = None
    order_number: int
    total_price: Decimal
    subtotal_price: Decimal | None = None
    discount_amount: Decimal = Decimal("0.00")
    shipping_fee: Decimal = Decimal("0.00")
    coupon_code: str | None = None
    currency: Currency = Currency.EGP
    expires_at: datetime | None = None
    status: OrderStatus
    shipping_address: str
    delivery_area: DeliveryArea | None = None
    created_at: datetime
    items: list[OrderItemRead] = Field(default_factory=list)

    payment: PaymentRead | None = None


class PlacedOrderRead(OrderRead):
    receipt_token: str


class OrderReceiptRead(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)

    order_number: int
    total_price: Decimal
    currency: Currency
    recipient_name: str
    recipient_phone: str
    shipping_address: str
    delivery_area: DeliveryArea | None
