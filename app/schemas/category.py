from pydantic import BaseModel


class CategoryCreate(BaseModel):
    category_name: str
    description: str | None


class CategoryUpdate(BaseModel):
    category_name: str | None = None
    description: str | None = None


class CategoryRead(BaseModel):
    category_name: str
    description: str | None
