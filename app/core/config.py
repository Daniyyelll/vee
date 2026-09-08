from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -- Core Settings --
    project_name: str = "Vee E-Commerce"

    # -- Database --
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_pwd: str

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://"
            f"{self.postgres_user}:{self.postgres_pwd}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    # -- Load Configuration --
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
