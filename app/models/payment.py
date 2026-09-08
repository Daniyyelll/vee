import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import Column, DateTime, Field, Numeric, Relationship, SQLModel, text

if TYPE_CHECKING:
    from .order import Order


class Currency(enum.StrEnum):
    EGP = "EGP"
    SAR = "SAR"
    AED = "AED"


class PaymentStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentMethod(enum.StrEnum):
    CASH = "Cash"
    INSTAPAY = "InstaPay"


class Payment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    amount: Decimal = Field(
        sa_column=Column(Numeric(10, 2)),
    )
    currency: Currency = Field(default=Currency.EGP)
    payment_status: PaymentStatus = Field(default=PaymentStatus.PENDING)

    provider_transaction_id: str = Field(default=None)

    payment_method: PaymentMethod = Field(default=PaymentMethod.CASH)

    order_id: uuid.UUID = Field(foreign_key="order.id")

    order: "Order" = Relationship(back_populates="payment")

    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )
