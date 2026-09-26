from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.app import create_app
from app.infrastructure.repositories import SqlUserRepository
from app.infrastructure.settings import AuthSettings, RateLimitSettings
from tests.fakes import FakeRedis
from tests.integration.conftest import (
    TEST_JWT_SECRET,
    savepoint_sessions,
    token_service,
)


def health(
    session_factory: Callable[[], Session], redis: FakeRedis
) -> tuple[int, dict[str, str]]:
    app = create_app(
        auth=AuthSettings(secret=TEST_JWT_SECRET),
        session_factory=session_factory,
        redis=redis,
        rate_limit=RateLimitSettings(storage_uri="memory://"),
    )
    with TestClient(app) as client:
        response = client.get("/api/health")
    return response.status_code, response.json()


def broken_database() -> Session:
    raise OperationalError("SELECT 1", {}, Exception("database unavailable"))


def test_all_dependencies_up(connection: Connection) -> None:
    assert health(savepoint_sessions(connection), FakeRedis()) == (
        200,
        {"status": "ok", "database": "ok", "redis": "ok"},
    )


def test_redis_down_is_degraded_but_serving(connection: Connection) -> None:
    # CRUD keeps working without Redis; only rate limiting and exports degrade.
    assert health(savepoint_sessions(connection), FakeRedis(up=False)) == (
        200,
        {"status": "degraded", "database": "ok", "redis": "unavailable"},
    )


@pytest.mark.parametrize("redis_up", [True, False])
def test_database_down_is_503(redis_up: bool) -> None:
    status, body = health(broken_database, FakeRedis(up=redis_up))

    assert status == 503
    assert body["status"] == "unavailable"
    assert body["database"] == "unavailable"


def test_health_is_public_and_documented(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert "/api/health" in client.get("/api/openapi.json").json()["paths"]


def test_database_check_sets_a_statement_timeout(connection: Connection) -> None:
    statements: list[str] = []
    event.listen(
        connection,
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )

    health(savepoint_sessions(connection), FakeRedis())

    assert any("statement_timeout" in s for s in statements)


def test_crud_keeps_working_with_redis_down(
    connection: Connection, session: Session
) -> None:
    user = SqlUserRepository(session).create(
        email="r@example.com",
        name="R",
        password_hash="h",  # pragma: allowlist secret
    )
    app = create_app(
        auth=AuthSettings(secret=TEST_JWT_SECRET),
        session_factory=savepoint_sessions(connection),
        redis=FakeRedis(up=False),
        rate_limit=RateLimitSettings(storage_uri="memory://"),
    )
    headers = {"Authorization": f"Bearer {token_service().issue(user.id)}"}

    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"title": "t"}, headers=headers)
        url = f"/api/v1/tasks/{created.json()['id']}"
        listed = client.get("/api/v1/tasks", headers=headers)
        read = client.get(url, headers=headers)
        patched = client.patch(url, json={"status": "completed"}, headers=headers)
        deleted = client.delete(url, headers=headers)

    assert created.status_code == 201
    assert listed.json()["total"] == 1
    assert read.status_code == 200
    assert patched.json()["status"] == "completed"
    assert deleted.status_code == 204
