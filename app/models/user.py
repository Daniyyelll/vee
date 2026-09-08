import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlmodel import Column, DateTime, Field, Relationship, SQLModel, text

if TYPE_CHECKING:
    from .cart import Cart
    from .order import Order
    from .review import Review


# User roles
class UserRole(str, Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    DELIVERY = "delivery"


# Actual models
class User(SQLModel, table=True):
    __tablename__ = "user"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str = Field()
    profile_picture: str | None = Field(default=None)
    address: str | None = Field(default=None)

    role: UserRole = Field(default=UserRole.CUSTOMER)
    active: bool = Field(default=True)
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=text("NOW()"),
            nullable=False,
        ),
    )

    # One-to-many relationship
    orders: list["Order"] = Relationship(back_populates="user")
    reviews: list["Review"] = Relationship(back_populates="user")

    # One-to-one relationship
    cart: Optional["Cart"] = Relationship(back_populates="user")
