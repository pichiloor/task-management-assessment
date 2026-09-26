"""Rate limits: login per client IP, the rest of the API per user.

Most tests use in-memory counters; one uses the real Redis from Compose and
one points at an unreachable Redis to check the in-memory fallback.
"""

import os
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy import Connection
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

LOGIN = "/api/v1/auth/token"
WRONG = "wrong"  # pragma: allowlist secret
BAD_LOGIN = {"username": "nobody@example.com", "password": WRONG}

MakeClient = Callable[..., AbstractContextManager[TestClient]]


@pytest.fixture
def make_client(connection: Connection) -> MakeClient:
    @contextmanager
    def make(
        settings: RateLimitSettings, client_ip: str = "198.51.100.1"
    ) -> Iterator[TestClient]:
        app = create_app(
            auth=AuthSettings(secret=TEST_JWT_SECRET),
            session_factory=savepoint_sessions(connection),
            redis=FakeRedis(),
            rate_limit=settings,
        )
        with TestClient(app, client=(client_ip, 50000)) as client:
            yield client

    return make


def memory(**limits: str) -> RateLimitSettings:
    return RateLimitSettings(storage_uri="memory://", **limits)


def auth_header(session: Session, email: str) -> dict[str, str]:
    user = SqlUserRepository(session).create(
        email=email,
        name=email,
        password_hash="h",  # pragma: allowlist secret
    )
    return {"Authorization": f"Bearer {token_service().issue(user.id)}"}


class TestLogin:
    def test_sixth_attempt_in_a_minute_is_rejected(
        self, make_client: MakeClient
    ) -> None:
        with make_client(memory()) as client:
            codes = [client.post(LOGIN, data=BAD_LOGIN).status_code for _ in range(6)]

            assert codes == [401] * 5 + [429]
            blocked = client.post(LOGIN, data=BAD_LOGIN)

        assert blocked.json() == {"detail": "Too many requests", "code": "rate_limited"}
        assert int(blocked.headers["Retry-After"]) > 0

    def test_limit_is_per_client_ip(self, make_client: MakeClient) -> None:
        settings = memory(login="2/minute")
        with make_client(settings, "198.51.100.1") as a:
            for _ in range(2):
                a.post(LOGIN, data=BAD_LOGIN)
            assert a.post(LOGIN, data=BAD_LOGIN).status_code == 429
            # Same app, different client address: separate counter.
            b = TestClient(a.app, client=("198.51.100.2", 50000))
            assert b.post(LOGIN, data=BAD_LOGIN).status_code == 401

    def test_limit_recovers_after_the_window(self, make_client: MakeClient) -> None:
        with make_client(memory(login="2/second")) as client:
            for _ in range(2):
                client.post(LOGIN, data=BAD_LOGIN)
            assert client.post(LOGIN, data=BAD_LOGIN).status_code == 429

            time.sleep(1.1)

            assert client.post(LOGIN, data=BAD_LOGIN).status_code == 401


class TestApi:
    def test_limit_is_per_user_not_per_ip(
        self, make_client: MakeClient, session: Session
    ) -> None:
        ana, bo = auth_header(session, "ana@x.io"), auth_header(session, "bo@x.io")
        with make_client(memory(api="3/minute")) as client:
            codes = [
                client.get("/api/v1/tasks", headers=ana).status_code for _ in range(4)
            ]

            assert codes == [200, 200, 200, 429]
            assert client.get("/api/v1/tasks", headers=bo).status_code == 200

    def test_invalid_tokens_are_limited_by_ip(self, make_client: MakeClient) -> None:
        # Rotating garbage tokens must not give an attacker fresh counters.
        with make_client(memory(api="2/minute")) as client:
            codes = [
                client.get(
                    "/api/v1/tasks", headers={"Authorization": f"Bearer junk{i}"}
                ).status_code
                for i in range(3)
            ]

        assert codes == [401, 401, 429]

    def test_health_and_docs_are_not_limited(self, make_client: MakeClient) -> None:
        with make_client(memory(api="1/minute")) as client:
            codes = {client.get("/api/health").status_code for _ in range(5)}
            docs = {client.get("/api/openapi.json").status_code for _ in range(5)}

        assert codes == {200}
        assert docs == {200}


class TestProxyHeaders:
    def test_forwarded_ip_is_used_only_from_a_trusted_proxy(
        self, make_client: MakeClient
    ) -> None:
        settings = memory(login="1/minute", trusted_proxies="172.28.0.0/16")

        with make_client(settings, "172.28.0.10") as proxy:
            first = proxy.post(
                LOGIN, data=BAD_LOGIN, headers={"X-Forwarded-For": "203.0.113.1"}
            )
            other = proxy.post(
                LOGIN, data=BAD_LOGIN, headers={"X-Forwarded-For": "203.0.113.2"}
            )
            again = proxy.post(
                LOGIN, data=BAD_LOGIN, headers={"X-Forwarded-For": "203.0.113.1"}
            )

        assert (first.status_code, other.status_code, again.status_code) == (
            401,
            401,
            429,
        )

    def test_forwarded_header_from_an_untrusted_client_is_ignored(
        self, make_client
    ) -> None:
        settings = memory(login="1/minute", trusted_proxies="172.28.0.0/16")

        with make_client(settings, "198.51.100.9") as client:
            client.post(
                LOGIN, data=BAD_LOGIN, headers={"X-Forwarded-For": "203.0.113.1"}
            )
            spoofed = client.post(
                LOGIN, data=BAD_LOGIN, headers={"X-Forwarded-For": "203.0.113.99"}
            )

        assert spoofed.status_code == 429


class TestStorage:
    def test_counters_live_in_redis(self, make_client: MakeClient) -> None:
        url = os.environ.get("TEST_REDIS_URL")
        if not url:
            pytest.skip("TEST_REDIS_URL is not set")
        server = redis.Redis.from_url(url)
        server.flushdb()

        with make_client(
            RateLimitSettings(storage_uri=url, login="2/minute")
        ) as client:
            codes = [client.post(LOGIN, data=BAD_LOGIN).status_code for _ in range(3)]

        assert codes == [401, 401, 429]
        assert server.dbsize() > 0
        server.flushdb()

    def test_login_stays_limited_when_redis_is_down(
        self, make_client: MakeClient
    ) -> None:
        unreachable = "redis://127.0.0.1:1/0"
        with make_client(
            RateLimitSettings(storage_uri=unreachable, login="2/minute")
        ) as client:
            codes = [client.post(LOGIN, data=BAD_LOGIN).status_code for _ in range(3)]

        assert codes == [401, 401, 429]


def test_default_limits_match_the_plan() -> None:
    settings = RateLimitSettings(storage_uri="memory://")

    assert (settings.login, settings.api) == ("5/minute", "120/minute")
