"""The API must refuse to start with a missing or weak JWT secret, instead of
failing later with a 500 on the first login."""

import pytest
from fastapi.testclient import TestClient
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


def test_engine_created_by_the_app_is_disposed_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    app = create_app()
    disposed: list[bool] = []
    monkeypatch.setattr(app.state.engine, "dispose", lambda: disposed.append(True))

    with TestClient(app):
        assert disposed == []

    assert disposed == [True]


def test_injected_session_factory_is_left_to_its_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    app = create_app(session_factory=lambda: None)  # type: ignore[arg-type,return-value]

    with TestClient(app):
        pass

    assert app.state.engine is None


def test_no_engine_is_created_if_setup_fails_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    created: list[object] = []
    monkeypatch.setattr("app.api.app.create_engine", lambda *a, **k: created.append(a))

    def broken_hash(self: object, password: str) -> str:
        raise RuntimeError("hashing unavailable")

    monkeypatch.setattr(
        "app.infrastructure.security.Argon2PasswordHasher.hash", broken_hash
    )

    with pytest.raises(RuntimeError):
        create_app()

    assert created == []
