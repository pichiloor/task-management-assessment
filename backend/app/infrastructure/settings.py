import re
from datetime import timedelta

from limits import parse_many
from pydantic import Field, SecretStr, field_validator
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


_SINGLE_LIMIT = re.compile(
    r"\s*[1-9]\d*\s*(?:/|per)\s*(?:[1-9]\d*\s+)?"
    r"(?:second|minute|hour|day)s?\s*"
)


class RateLimitSettings(BaseSettings):
    """Limits use the `limits` notation, e.g. "5/minute". The storage defaults
    to REDIS_URL. `trusted_proxies` lists the addresses (or CIDR ranges)
    allowed to set X-Forwarded-For, comma-separated."""

    model_config = SettingsConfigDict(
        env_prefix="RATE_LIMIT_", hide_input_in_errors=True
    )

    login: str = "5/minute"
    api: str = "120/minute"
    storage_uri: str | None = None
    trusted_proxies: str = "127.0.0.1"
    key_prefix: str = Field(default="task-management", pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("login", "api")
    @classmethod
    def _single_positive_limit(cls, value: str) -> str:
        # `limits` silently keeps only the first of "a; b" and rewrites a zero
        # period ("5/0 seconds") as one, so the notation is checked strictly.
        if not _SINGLE_LIMIT.fullmatch(value) or len(parse_many(value)) != 1:
            raise ValueError(
                "expected one limit with a positive amount and period, "
                "e.g. '5/minute' or '10/5 seconds'"
            )
        return value
