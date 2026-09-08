import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlmodel import Column, DateTime, Field, Relationship, SQLModel, text

if TYPE_CHECKING:
    from .product import Product
    from .user import User


class Review(SQLModel, table=True):
    __tablename__ = "review"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    rating: int = Field(ge=1, le=5)

    comment: str | None = Field(default=None)

    username: None = Field(default=None)

    created_at: datetime = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )
    product_id: uuid.UUID = Field(foreign_key="product.id")
    user_id: uuid.UUID = Field(foreign_key="user.id")

    product: "Product" = Relationship(back_populates="reviews")
    user: "User" = Relationship(back_populates="reviews")
