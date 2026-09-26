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
    "REDIS_URL": "redis://localhost:6379/0",
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


def test_redis_client_created_by_the_app_is_closed_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    app = create_app()
    closed: list[bool] = []
    monkeypatch.setattr(app.state.owned_redis, "close", lambda: closed.append(True))

    with TestClient(app):
        assert closed == []

    assert closed == [True]


def test_invalid_redis_url_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    monkeypatch.setenv("REDIS_URL", "http://not-redis")

    with pytest.raises(ValidationError):
        create_app()


def test_database_connections_have_bounded_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A PostgreSQL server that stops answering must not hang requests forever.
    monkeypatch.setenv("JWT_SECRET", "k" * 32)
    calls: list[dict[str, object]] = []

    def fake_create_engine(url: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return type("E", (), {"dispose": lambda self: None})()

    monkeypatch.setattr("app.api.app.create_engine", fake_create_engine)

    create_app()

    (kwargs,) = calls
    connect_args = kwargs["connect_args"]
    assert isinstance(connect_args, dict)
    assert 0 < connect_args["connect_timeout"] <= 5
    assert 0 < connect_args["tcp_user_timeout"] <= 10_000
    assert 0 < kwargs["pool_timeout"] <= 10  # type: ignore[operator]
