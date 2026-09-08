import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import (
    BigInteger,
    Column,
    DateTime,
    Field,
    Numeric,
    Relationship,
    Sequence,
    SQLModel,
    text,
)

if TYPE_CHECKING:
    from .order_item import OrderItem
    from .payment import Payment
    from .user import User


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Order(SQLModel, table=True):
    __tablename__ = "order"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    order_number: int = Field(
        sa_column=Column(
            BigInteger,
            Sequence("order_number_seq"),
            unique=True,
            nullable=False,
        )
    )

    total_price: Decimal = Field(sa_column=Column(Numeric(10, 2)))
    shipping_address: str = Field()
    status: OrderStatus = Field(default=OrderStatus.PENDING)

    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )

    # Relation
    user_id: uuid.UUID = Field(foreign_key="user.id")

    # Relationships
    user: "User" = Relationship(back_populates="orders")
    payment: "Payment" = Relationship(back_populates="orders")
    order_items: list["OrderItem"] = Relationship(back_populates="order")
