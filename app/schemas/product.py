from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from app.schemas.review import ReviewResponse


class ProductCreate(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
    )

    product_name: str
    description: str | None = None
    price: Decimal = Field(gt=0)
    stock_quantity: int = Field(ge=0)
    category_id: UUID


class ProductRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
    )

    product_name: str
    description: str | None
    price: Decimal
    stock_quantity: int = Field(ge=0)
    image_url: str | None


class ProductDetails(ProductRead):
    reviews: list[ReviewResponse] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    product_name: str | None = None
    description: str | None = None
    price: Decimal | None = None
    stock_quantity: int | None = Field(default=None, ge=0)
    image_url: str | None = None
