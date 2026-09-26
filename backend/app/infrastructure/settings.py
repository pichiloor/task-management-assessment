from datetime import timedelta
from functools import lru_cache

from pydantic import Field, SecretStr
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


class AuthSettings(BaseSettings):
    """The secret has no default: startup fails if it is missing or short."""

    model_config = SettingsConfigDict(env_prefix="JWT_")

    secret: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=60, gt=0, le=24 * 60)

    @property
    def jwt_secret(self) -> SecretStr:
        return self.secret

    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_expire_minutes)


@lru_cache
def auth_settings() -> AuthSettings:
    return AuthSettings()
