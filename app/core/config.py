from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # -- Security --
    secret_jwt_key: str
    algorithm: str

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
