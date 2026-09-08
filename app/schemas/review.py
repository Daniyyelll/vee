import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ReviewCreate(BaseModel):
    product_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
    )


class ReviewResponse(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str
    username: str
    created_at: datetime
    product_id: uuid.UUID
    user_id: uuid.UUID

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
    )
