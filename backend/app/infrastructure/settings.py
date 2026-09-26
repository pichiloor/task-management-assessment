from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DatabaseSettings(BaseSettings):
    """Read from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    user: str
    password: str
    db: str
    host: str = "db"
    port: int = 5432

    @property
    def url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.db,
        )


@lru_cache
def database_settings() -> DatabaseSettings:
    return DatabaseSettings()
