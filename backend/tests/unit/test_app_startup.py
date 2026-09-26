"""The API must refuse to start with a missing or weak JWT secret, instead of
failing later with a 500 on the first login."""

import pytest
from pydantic import ValidationError

from app.api.app import create_app

DB_ENV = {
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "pw",  # pragma: allowlist secret
    "POSTGRES_DB": "app",
}


@pytest.fixture(autouse=True)
def database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in DB_ENV.items():
        monkeypatch.setenv(key, value)


def test_missing_jwt_secret_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)

    with pytest.raises(ValidationError):
        create_app()


def test_short_jwt_secret_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "too-short")  # pragma: allowlist secret

    with pytest.raises(ValidationError):
        create_app()


def test_valid_configuration_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "k" * 32)

    assert create_app().title == "Task Management API"
