from pydantic import BaseModel, ConfigDict, EmailStr
from pydantic.alias_generators import to_camel

from app.domain.enums import UserRole


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole | None = UserRole.CUSTOMER


class UserRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    name: str
    email: EmailStr
    role: UserRole
    active: bool = True
    address: str | None = None


class UserLogin(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    email: EmailStr
    password: str


class TokenData(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserRead


class UserUpdate(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    name: str | None = None
    address: str | None = None


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    old_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,  # Convert Python fields from snake_case to camelCase
        validate_by_name=True,
        validate_by_alias=True,
    )

    code: str
    new_password: str
