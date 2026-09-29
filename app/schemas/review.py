import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class ReviewCreate(BaseModel):
    product_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=1, max_length=5000)

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


class ReviewUpdate(BaseModel):
    model_config = ReviewCreate.model_config

    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, min_length=1, max_length=5000)

    @model_validator(mode="after")
    def valid_changes(self):
        changes = self.model_dump(exclude_unset=True)
        if not changes or any(value is None for value in changes.values()):
            raise ValueError("Provide rating or comment; neither can be null")
        return self


class ReviewResponse(BaseModel):
    id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None
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
