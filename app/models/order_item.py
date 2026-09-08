import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import CheckConstraint, Column, Field, Numeric, Relationship, SQLModel

if TYPE_CHECKING:
    from .order import Order
    from .product import Product


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    quantity: int = Field(default=1)
    unit_price: Decimal = Field(sa_column=Column(Numeric(10, 2)))

    is_reviewed: bool = Field(default=False)

    order_id: uuid.UUID = Field(foreign_key="order.id")
    product_id: uuid.UUID = Field(foreign_key="product.id")

    # Relationships
    product: "Product" = Relationship(back_populates="order_items")
    order: "Order" = Relationship(back_populates="order_items")

    # Constraints
    __table_args__ = (
        CheckConstraint("quantity > 0", name="check_positive_quantity"),
        CheckConstraint("price > 0", name="check_positive_price"),
    )
