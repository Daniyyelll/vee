from uuid import UUID

from pydantic import BaseModel, Field, model_validator, ConfigDict
from pydantic.alias_generators import to_camel


class CategoryCreate(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    category_name: str
    description: str | None


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    category_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "CategoryUpdate":
        if not self.model_fields_set:
            raise ValueError("Provide at least one category field to update.")

        if "category_name" in self.model_fields_set and self.category_name is None:
            raise ValueError("category_name cannot be null.")

        return self


class CategoryRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )
    id: UUID
    category_name: str
    description: str | None
