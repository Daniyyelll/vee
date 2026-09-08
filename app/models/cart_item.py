import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from .cart import Cart
    from .product import Product


class CartItem(SQLModel, table=True):
    __tablename__ = "cart_item"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)

    cart_id: uuid.UUID = Field(foreign_key="cart.id")
    product_id: uuid.UUID = Field(foreign_key="product.id")
    quantity: int = Field(default=1)

    # Relationship
    cart: "Cart" = Relationship(back_populates="cart_items")
    product: "Product" = Relationship(back_populates="cart_items")
