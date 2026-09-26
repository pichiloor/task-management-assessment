from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import AuthSettings

SECRET = "s" * 32  # pragma: allowlist secret
OTHER_SECRET = "o" * 32  # pragma: allowlist secret


def tokens(*, now: datetime | None = None, ttl_minutes: int = 60) -> JwtTokenService:
    fixed = now or datetime.now(UTC)
    return JwtTokenService(
        secret=SECRET, ttl=timedelta(minutes=ttl_minutes), clock=lambda: fixed
    )


class TestArgon2:
    def test_hash_is_salted_and_verifiable(self) -> None:
        hasher = Argon2PasswordHasher()
        first, second = hasher.hash("pw"), hasher.hash("pw")

        assert first != second
        assert first.startswith("$argon2id$")
        assert hasher.verify(first, "pw")
        assert not hasher.verify(first, "other")

    def test_malformed_hash_is_a_failed_verification(self) -> None:
        assert not Argon2PasswordHasher().verify("not-a-hash", "pw")


class TestJwt:
    def test_round_trip(self) -> None:
        service = tokens()

        assert service.subject(service.issue(42)) == 42

    def test_expiry_is_issue_time_plus_ttl(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        claims = jwt.decode(
            tokens(now=now, ttl_minutes=15).issue(1),
            SECRET,
            algorithms=["HS256"],
        )

        assert claims["exp"] - claims["iat"] == 15 * 60
        assert claims["sub"] == "1"

    def test_expired_token_is_rejected(self) -> None:
        issued = datetime.now(UTC) - timedelta(minutes=61)

        assert tokens().subject(tokens(now=issued).issue(1)) is None

    def test_tampered_payload_is_rejected(self) -> None:
        header, _, signature = tokens().issue(1).split(".")
        forged_payload = jwt.utils.base64url_encode(b'{"sub":"2","exp":9999999999}')

        forged = f"{header}.{forged_payload.decode()}.{signature}"

        assert tokens().subject(forged) is None

    @pytest.mark.parametrize(
        ("key", "algorithm"),
        [(OTHER_SECRET, "HS256"), (SECRET, "HS512")],
    )
    def test_wrong_key_or_algorithm_is_rejected(self, key: str, algorithm: str) -> None:
        exp = datetime.now(UTC) + timedelta(minutes=5)
        token = jwt.encode({"sub": "1", "exp": exp}, key, algorithm=algorithm)

        assert tokens().subject(token) is None

    def test_unsigned_token_is_rejected(self) -> None:
        exp = datetime.now(UTC) + timedelta(minutes=5)
        token = jwt.encode({"sub": "1", "exp": exp}, None, algorithm="none")

        assert tokens().subject(token) is None

    @pytest.mark.parametrize(
        "claims",
        [
            {"sub": "1"},  # no expiry
            {"exp": 9999999999},  # no subject
            {"sub": "abc", "exp": 9999999999},
            {"sub": "-3", "exp": 9999999999},
        ],
    )
    def test_missing_or_malformed_claims_are_rejected(
        self, claims: dict[str, object]
    ) -> None:
        token = jwt.encode(claims, SECRET, algorithm="HS256")

        assert tokens().subject(token) is None

    def test_garbage_is_rejected(self) -> None:
        assert tokens().subject("not.a.jwt") is None


class TestAuthSettings:
    def test_reads_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", SECRET)
        monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")

        settings = AuthSettings()

        assert settings.jwt_secret.get_secret_value() == SECRET
        assert settings.access_token_ttl == timedelta(minutes=15)

    def test_missing_secret_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(ValidationError):
            AuthSettings()

    def test_short_secret_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", "s" * 31)
        with pytest.raises(ValidationError):
            AuthSettings()

    def test_secret_is_hidden_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", SECRET)

        assert SECRET not in repr(AuthSettings())
