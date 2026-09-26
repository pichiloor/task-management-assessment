import pytest

from app.application.auth import AuthService
from app.domain.errors import AuthenticationError
from app.domain.user import User
from tests.fakes import FakePasswordHasher, FakeTokenService, InMemoryUserRepository

ACTIVE, INACTIVE = 1, 2


def user(user_id: int, email: str, *, active: bool = True) -> User:
    return User(
        id=user_id,
        email=email,
        name=email.split("@")[0],
        password_hash="hashed:right",  # pragma: allowlist secret
        is_active=active,
    )


@pytest.fixture
def hasher() -> FakePasswordHasher:
    return FakePasswordHasher()


@pytest.fixture
def auth(hasher: FakePasswordHasher) -> AuthService:
    users = InMemoryUserRepository(
        [
            user(ACTIVE, "ana@example.com"),
            user(INACTIVE, "old@example.com", active=False),
        ]
    )
    return AuthService(
        users=users,
        hasher=hasher,
        tokens=FakeTokenService(),
        dummy_hash="hashed:never-matches",  # pragma: allowlist secret
    )


class TestLogin:
    def test_valid_credentials_return_a_token_for_the_user(
        self, auth: AuthService
    ) -> None:
        token = auth.login("ana@example.com", "right")

        assert auth.current_user(token).id == ACTIVE

    def test_email_is_matched_case_insensitively(self, auth: AuthService) -> None:
        assert auth.login("  Ana@Example.COM ", "right")

    @pytest.mark.parametrize(
        ("email", "password"),
        [
            ("ana@example.com", "wrong"),
            ("nobody@example.com", "right"),
            ("old@example.com", "right"),
        ],
    )
    def test_failures_are_indistinguishable(
        self, auth: AuthService, email: str, password: str
    ) -> None:
        with pytest.raises(AuthenticationError) as exc:
            auth.login(email, password)
        assert exc.value.code == "invalid_credentials"
        assert exc.value.detail == "Incorrect email or password"

    def test_unknown_email_still_runs_a_hash_verification(
        self, auth: AuthService, hasher: FakePasswordHasher
    ) -> None:
        # Otherwise response time reveals which emails are registered.
        with pytest.raises(AuthenticationError):
            auth.login("nobody@example.com", "right")

        assert len(hasher.verified) == 1


class TestCurrentUser:
    def test_checking_a_token_never_hashes(
        self, auth: AuthService, hasher: FakePasswordHasher
    ) -> None:
        # Argon2 costs ~64 MiB per hash; token checks run on every request.
        auth.current_user(f"token:{ACTIVE}")

        assert hasher.hashed == []
        assert hasher.verified == []

    @pytest.mark.parametrize("token", ["", "garbage", "token:", "token:999"])
    def test_invalid_or_unknown_subject_is_rejected(
        self, auth: AuthService, token: str
    ) -> None:
        with pytest.raises(AuthenticationError) as exc:
            auth.current_user(token)
        assert exc.value.code == "invalid_token"

    def test_token_of_a_deactivated_user_is_rejected(self, auth: AuthService) -> None:
        with pytest.raises(AuthenticationError) as exc:
            auth.current_user(f"token:{INACTIVE}")
        assert exc.value.code == "invalid_token"
