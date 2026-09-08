import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import Column, Field, Numeric, Relationship, SQLModel

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

    total_price: Decimal = Field(sa_column=Column(Numeric(10, 2)))
    shipping_address: str = Field()
    status: OrderStatus = Field(default=OrderStatus.PENDING)

    # Relation
    user_id: uuid.UUID = Field(foreign_key="user.id")

    # Relationships
    user: "User" = Relationship(back_populates="orders")
    payment: "Payment" = Relationship(back_populates="orders")
    order_items: list["OrderItem"] = Relationship(back_populates="order")
