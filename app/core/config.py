from decimal import Decimal
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import Currency


class Settings(BaseSettings):
    # -- Core Settings --
    project_name: str = "Vee E-Commerce"
    environment: Literal["development", "test", "production"] = "development"
    max_request_body_bytes: int = Field(default=6 * 1024 * 1024, ge=1024)

    # -- Supabase Storage --
    supabase_url: str
    supabase_service_role_key: str
    supabase_product_bucket: str = "product-images"

    # URL
    BACKEND_URL: str
    FRONTEND_URL: str
    vercel_url: str | None = None

    # -- Database --
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_pwd: str
    database_sslmode: Literal[
        "disable", "prefer", "require", "verify-ca", "verify-full"
    ] = "prefer"
    database_connect_timeout: float = Field(default=10, gt=0, le=60)
    database_command_timeout: float = Field(default=30, gt=0, le=300)
    database_statement_timeout_ms: int = Field(default=30000, ge=1000, le=300000)
    database_acquire_timeout: float = Field(default=10, gt=0, le=60)

    # Currency is chosen by the store, never by checkout input.
    payment_currency: Currency = Currency.EGP
    shipping_fee: Decimal = Field(
        default=Decimal("50.00"), ge=0, le=99999999, decimal_places=2
    )

    # -- Security --
    secret_jwt_key: str = Field(min_length=32)
    checkout_hmac_key: str | None = Field(default=None, min_length=32)
    algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "vee-api"
    jwt_audience: str = "vee-web"
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
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_pwd, safe="")
        database = quote(self.postgres_db, safe="")
        query = urlencode({"ssl": self.database_sslmode})
        return (
            f"postgresql+asyncpg://"
            f"{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{database}?{query}"
        )

    @property
    def ASYNCPG_DATABASE_URL(self) -> str:
        """Return a driver-neutral PostgreSQL DSN for asyncpg."""
        return self.DATABASE_URL.replace(
            "postgresql+asyncpg://", "postgresql://", 1
        ).replace("?ssl=", "?sslmode=", 1)

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment != "production":
            return self

        insecure_urls = [
            name
            for name, value in (
                ("BACKEND_URL", self.BACKEND_URL),
                ("FRONTEND_URL", self.FRONTEND_URL),
            )
            if urlsplit(value).scheme != "https"
        ]
        if insecure_urls:
            raise ValueError(
                f"Production requires HTTPS for: {', '.join(insecure_urls)}"
            )
        if not self.checkout_hmac_key:
            raise ValueError("CHECKOUT_HMAC_KEY is required in production")
        if not self.REFRESH_COOKIE_SECURE:
            raise ValueError("Secure refresh cookies are required in production")
        if self.database_sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Production database connections must require TLS")
        return self

    # -- Load Configuration --
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False
    )


settings = Settings()
