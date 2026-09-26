from collections.abc import Callable
from datetime import datetime, timedelta

import jwt
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_ALGORITHM = "HS256"
_MAX_USER_ID = 2**31 - 1  # PostgreSQL integer primary key


class Argon2PasswordHasher:
    """argon2id with the library's recommended parameters."""

    def __init__(self) -> None:
        self._argon2 = _Argon2()

    def hash(self, password: str) -> str:
        return self._argon2.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


class JwtTokenService:
    """HS256 access tokens. Only HS256 is accepted when decoding, which rules
    out `alg: none` and algorithm-confusion tokens."""

    def __init__(
        self, *, secret: str, ttl: timedelta, clock: Callable[[], datetime]
    ) -> None:
        self._secret = secret
        self._ttl = ttl
        self._clock = clock

    def issue(self, user_id: int) -> str:
        now = self._clock()
        claims = {"sub": str(user_id), "iat": now, "exp": now + self._ttl}
        return jwt.encode(claims, self._secret, algorithm=_ALGORITHM)

    def subject(self, token: str) -> int | None:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[_ALGORITHM],
                options={"require": ["exp", "sub"]},
            )
        except jwt.InvalidTokenError:
            return None
        sub = claims["sub"]
        # Length check first: int() on thousands of digits raises ValueError.
        if not isinstance(sub, str) or not sub.isdecimal() or len(sub) > 10:
            return None
        user_id = int(sub)
        return user_id if 1 <= user_id <= _MAX_USER_ID else None
