from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    status_code: int
    message: str
    data: T | None = None

    model_config = ConfigDict(from_attributes=True)
