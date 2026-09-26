from app.application.ports import PasswordHasher, TokenService, UserRepository
from app.domain.errors import AuthenticationError
from app.domain.user import User


class AuthService:
    def __init__(
        self, *, users: UserRepository, hasher: PasswordHasher, tokens: TokenService
    ) -> None:
        self._users = users
        self._hasher = hasher
        self._tokens = tokens
        # Verified against when the email is unknown, so that the response
        # time does not reveal which emails are registered.
        self._dummy_hash = hasher.hash("timing-equalizer")

    def login(self, email: str, password: str) -> str:
        user = self._users.get_by_email(email)
        password_hash = user.password_hash if user else self._dummy_hash
        password_ok = self._hasher.verify(password_hash, password)
        if user is None or not password_ok or not user.is_active:
            raise AuthenticationError(
                "invalid_credentials", "Incorrect email or password"
            )
        return self._tokens.issue(user.id)

    def current_user(self, token: str) -> User:
        user_id = self._tokens.subject(token)
        user = self._users.get(user_id) if user_id is not None else None
        if user is None or not user.is_active:
            raise AuthenticationError("invalid_token", "Invalid or expired token")
        return user
