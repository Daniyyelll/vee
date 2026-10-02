from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import Currency


class Settings(BaseSettings):
    # -- Core Settings --
    project_name: str = "Vee E-Commerce"
    product_upload_dir: Path = Path(__file__).resolve().parents[2] / "uploads/products"

    # URL
    BACKEND_URL: str
    FRONTEND_URL: str

    # -- Database --
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_pwd: str

    # Currency is chosen by the store, never by checkout input.
    payment_currency: Currency = Currency.EGP
    shipping_fee: Decimal = Field(
        default=Decimal("50.00"), ge=0, le=99999999, decimal_places=2
    )

    # -- Security --
    secret_jwt_key: str = Field(min_length=32)
    checkout_hmac_key: str | None = Field(default=None, min_length=32)
    algorithm: Literal["HS256"] = "HS256"
    refresh_cookie_secure: bool | None = None
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @property
    def REFRESH_COOKIE_SECURE(self) -> bool:
        if self.refresh_cookie_secure is not None:
            return self.refresh_cookie_secure
        return urlsplit(self.BACKEND_URL).hostname not in ("localhost", "127.0.0.1")

    # SMTP
    mail_user: str
    mail_pass: str
    mail_host: str
    mail_port: str
    mail_from: str

    @property
    def RESET_PASSWORD_URL(self) -> str:
        return f"{self.FRONTEND_URL}/reset-password?token="

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_pwd}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    @property
    def ASYNCPG_DATABASE_URL(self) -> str:
        """Return a driver-neutral PostgreSQL DSN for asyncpg."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

    # -- Load Configuration --
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False
    )


settings = Settings()
