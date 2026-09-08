import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .cart_item import CartItem
    from .user import User


class Cart(SQLModel, table=True):
    __tablename__ = "cart"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="user.id", unique=True)

    # Relationship
    user: "User" = Relationship(back_populates="cart")
    cart_items: list["CartItem"] = Relationship(back_populates="cart")
