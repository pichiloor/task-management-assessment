from datetime import timedelta

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DatabaseSettings(BaseSettings):
    """Read from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_", hide_input_in_errors=True)

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


class AuthSettings(BaseSettings):
    """The secret has no default: create_app fails if it is missing or short.
    Invalid input is never echoed in the validation error."""

    model_config = SettingsConfigDict(env_prefix="JWT_", hide_input_in_errors=True)

    secret: SecretStr = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=60, gt=0, le=24 * 60)

    @property
    def jwt_secret(self) -> SecretStr:
        return self.secret

    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_expire_minutes)


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", hide_input_in_errors=True)

    url: str = Field(pattern=r"^rediss?://")
