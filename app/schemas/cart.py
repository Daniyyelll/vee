import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CartItemRead(BaseModel):
    product_id: uuid.UUID
    product_name: str
    product_price: Decimal
    product_image: str | None = None
    quantity: int
    subtotal: Decimal

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )


class AddToCartRequest(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, gt=0)


class CartRead(BaseModel):
    user_id: uuid.UUID
    items: list[CartItemRead] = Field(default_factory=list)
    total_quantity: int
    total_price: Decimal

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        from_attributes=True,
    )
