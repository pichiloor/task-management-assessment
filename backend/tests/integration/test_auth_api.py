from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.infrastructure.models import UserRow
from app.infrastructure.repositories import SqlUserRepository
from app.infrastructure.security import Argon2PasswordHasher
from tests.integration.conftest import token_service

PASSWORD = "correct horse battery"  # pragma: allowlist secret


@pytest.fixture
def users(session: Session) -> SqlUserRepository:
    return SqlUserRepository(session)


@pytest.fixture
def ana(users: SqlUserRepository) -> int:
    hashed = Argon2PasswordHasher().hash(PASSWORD)
    return users.create(email="ana@example.com", name="Ana", password_hash=hashed).id


def login(client: TestClient, email: str, password: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )
    return {"status": response.status_code, "json": response.json(), "r": response}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestLogin:
    def test_valid_login_returns_a_bearer_token(
        self, client: TestClient, ana: int
    ) -> None:
        result = login(client, "ana@example.com", PASSWORD)

        assert result["status"] == 200
        body = result["json"]
        assert isinstance(body, dict)
        assert body["token_type"] == "bearer"
        assert isinstance(body["access_token"], str)

    @pytest.mark.parametrize(
        ("email", "password"),
        [("ana@example.com", "wrong"), ("nobody@example.com", PASSWORD)],
    )
    def test_bad_credentials_get_the_same_401(
        self, client: TestClient, ana: int, email: str, password: str
    ) -> None:
        result = login(client, email, password)

        assert result["status"] == 401
        assert result["json"] == {
            "detail": "Incorrect email or password",
            "code": "invalid_credentials",
        }
        assert result["r"].headers["WWW-Authenticate"] == "Bearer"  # type: ignore[attr-defined]

    def test_inactive_user_cannot_log_in(
        self, client: TestClient, users: SqlUserRepository
    ) -> None:
        hashed = Argon2PasswordHasher().hash(PASSWORD)
        users.create(
            email="old@example.com", name="Old", password_hash=hashed, is_active=False
        )

        assert login(client, "old@example.com", PASSWORD)["status"] == 401

    def test_missing_fields_are_a_validation_error(self, client: TestClient) -> None:
        assert client.post("/api/v1/auth/token", data={}).status_code == 422


class TestCurrentUser:
    def test_me_returns_profile_without_password_hash(
        self, client: TestClient, ana: int
    ) -> None:
        token = login(client, "ana@example.com", PASSWORD)["json"]["access_token"]  # type: ignore[index]

        response = client.get("/api/v1/users/me", headers=bearer(token))

        assert response.status_code == 200
        assert response.json() == {"id": ana, "email": "ana@example.com", "name": "Ana"}

    def test_missing_token(self, client: TestClient) -> None:
        response = client.get("/api/v1/users/me")

        assert response.status_code == 401
        assert response.json()["code"] == "not_authenticated"
        assert response.headers["WWW-Authenticate"] == "Bearer"

    @pytest.mark.parametrize("token", ["garbage", "a.b.c"])
    def test_malformed_token(self, client: TestClient, token: str) -> None:
        response = client.get("/api/v1/users/me", headers=bearer(token))

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_token"

    def test_expired_token(self, client: TestClient, ana: int) -> None:
        old = token_service(datetime.now(UTC) - timedelta(hours=2)).issue(ana)

        response = client.get("/api/v1/users/me", headers=bearer(old))

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_token"

    def test_tampered_token(self, client: TestClient, ana: int) -> None:
        token = token_service().issue(ana)
        tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")

        response = client.get("/api/v1/users/me", headers=bearer(tampered))

        assert response.status_code == 401

    def test_deactivated_user_loses_access(
        self, client: TestClient, session: Session, ana: int
    ) -> None:
        token = token_service().issue(ana)
        session.get_one(UserRow, ana).is_active = False
        session.flush()

        assert client.get("/api/v1/users/me", headers=bearer(token)).status_code == 401


class TestAssignableUsers:
    def test_lists_active_users_with_id_and_name_only(
        self, client: TestClient, users: SqlUserRepository, ana: int
    ) -> None:
        unused = "h"  # pragma: allowlist secret
        bo = users.create(email="bo@example.com", name="Bo", password_hash=unused)
        users.create(
            email="gone@example.com",
            name="Gone",
            password_hash=unused,
            is_active=False,
        )

        response = client.get(
            "/api/v1/users", headers=bearer(token_service().issue(ana))
        )

        assert response.status_code == 200
        assert response.json() == [
            {"id": ana, "name": "Ana"},
            {"id": bo.id, "name": "Bo"},
        ]

    def test_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/api/v1/users").status_code == 401


def test_openapi_documents_the_password_flow(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()

    flows = schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]
    assert flows["password"]["tokenUrl"] == "/api/v1/auth/token"
    assert client.get("/api/docs").status_code == 200
