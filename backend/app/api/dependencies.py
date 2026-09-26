"""Request-scoped wiring: one database session and transaction per request,
and the services built on top of it. Tests override get_session and
get_token_service."""

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.auth import AuthService
from app.application.ports import TokenService
from app.application.tasks import TaskService
from app.domain.errors import AuthenticationError
from app.domain.user import User
from app.infrastructure.repositories import SqlTaskRepository, SqlUserRepository
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import auth_settings, database_settings

TOKEN_URL = "/api/v1/auth/token"

_oauth2 = OAuth2PasswordBearer(tokenUrl=TOKEN_URL, auto_error=False)


def utc_now() -> datetime:
    return datetime.now(UTC)


@lru_cache
def _engine() -> Engine:
    return create_engine(database_settings().url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Commits when the request succeeds, rolls back on any exception."""
    with _session_factory()() as session, session.begin():
        yield session


@lru_cache
def _hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher()


def get_token_service() -> TokenService:
    settings = auth_settings()
    return JwtTokenService(
        secret=settings.jwt_secret.get_secret_value(),
        ttl=settings.access_token_ttl,
        clock=utc_now,
    )


SessionDep = Annotated[Session, Depends(get_session)]


def get_auth_service(
    session: SessionDep,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AuthService:
    return AuthService(
        users=SqlUserRepository(session), hasher=_hasher(), tokens=tokens
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def get_current_user(
    auth: AuthServiceDep, token: Annotated[str | None, Depends(_oauth2)]
) -> User:
    if not token:
        raise AuthenticationError("not_authenticated", "Not authenticated")
    return auth.current_user(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_task_service(session: SessionDep) -> TaskService:
    return TaskService(
        tasks=SqlTaskRepository(session),
        users=SqlUserRepository(session),
        clock=utc_now,
    )


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
