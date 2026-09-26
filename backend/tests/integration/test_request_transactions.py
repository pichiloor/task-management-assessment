from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, event
from sqlalchemy.orm import Session

from app.api.app import create_app
from app.infrastructure.repositories import SqlUserRepository
from app.infrastructure.settings import AuthSettings, RateLimitSettings
from tests.fakes import FakeExportQueue, FakeRedis
from tests.integration.conftest import (
    TEST_JWT_SECRET,
    savepoint_sessions,
    token_service,
)


@pytest.fixture
def failing_commit_client(connection: Connection) -> Iterator[TestClient]:
    make_session = savepoint_sessions(connection)

    def factory() -> Session:
        session = make_session()

        @event.listens_for(session, "before_commit")
        def fail(_: Session) -> None:
            raise RuntimeError("simulated commit failure")

        return session

    app = create_app(
        auth=AuthSettings(secret=TEST_JWT_SECRET),
        session_factory=factory,
        redis=FakeRedis(),
        rate_limit=RateLimitSettings(storage_uri="memory://"),
        export_queue=FakeExportQueue(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_commit_failure_is_reported_to_the_client(
    failing_commit_client: TestClient, session: Session
) -> None:
    # The transaction must end before the response is sent; otherwise the
    # client would already have a 200 when the commit fails.
    user = SqlUserRepository(session).create(
        email="t@example.com",
        name="T",
        password_hash="h",  # pragma: allowlist secret
    )

    response = failing_commit_client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token_service().issue(user.id)}"},
    )

    assert response.status_code == 500
