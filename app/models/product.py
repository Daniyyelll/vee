import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlmodel import (
    CheckConstraint,
    Column,
    DateTime,
    Field,
    Numeric,
    Relationship,
    SQLModel,
    text,
)

if TYPE_CHECKING:
    from .cart_item import CartItem
    from .category import Category
    from .order_item import OrderItem
    from .review import Review


class Product(SQLModel, table=True):
    __tablename__ = "product"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    product_name: str = Field(index=True, unique=True)
    description: str | None = None
    price: Decimal = Field(sa_column=Column(Numeric(6, 2)))
    stock_quantity: int = Field()
    image_url: str | None = None
    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )
    category_id: uuid.UUID = Field(foreign_key="category.id")

    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="check_nonnegative_stock_quantity"),
        CheckConstraint("price > 0", name="check_positive_price"),
    )

    # Many-to-one relationship
    category: "Category" = Relationship(back_populates="products")

    # One-to-many relationship
    order_items: list["OrderItem"] = Relationship(back_populates="product")
    reviews: list["Review"] = Relationship(
        back_populates="product",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    cart_items: list["CartItem"] = Relationship(back_populates="product")
