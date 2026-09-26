from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.app import create_app
from app.infrastructure.settings import AuthSettings
from tests.fakes import FakeRedis
from tests.integration.conftest import TEST_JWT_SECRET, savepoint_sessions


def health(
    session_factory: Callable[[], Session], redis: FakeRedis
) -> tuple[int, dict[str, str]]:
    app = create_app(
        auth=AuthSettings(secret=TEST_JWT_SECRET),
        session_factory=session_factory,
        redis=redis,
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
