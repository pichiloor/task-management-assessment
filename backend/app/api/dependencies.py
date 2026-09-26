"""Request-scoped wiring. Process-wide objects (session factory, token service,
password hasher) live on `app.state`, set up by `create_app`."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.application.auth import AuthService
from app.application.exports import ExportService
from app.application.ports import TokenService
from app.application.tasks import TaskService
from app.domain.errors import AuthenticationError
from app.domain.user import User
from app.infrastructure.repositories import (
    SqlTaskRepository,
    SqlUserRepository,
    sql_unit_of_work,
)

TOKEN_URL = "/api/v1/auth/token"

_oauth2 = OAuth2PasswordBearer(tokenUrl=TOKEN_URL, auto_error=False)


def utc_now() -> datetime:
    return datetime.now(UTC)


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request: commits on success, rolls back on error."""
    with request.app.state.session_factory() as session, session.begin():
        yield session


# scope="function" ends the transaction before the response is sent, so a
# failed commit becomes a 500 instead of following an already-sent 200.
SessionDep = Annotated[Session, Depends(get_session, scope="function")]


def get_token_service(request: Request) -> TokenService:
    tokens: TokenService = request.app.state.tokens
    return tokens


def get_auth_service(
    request: Request,
    session: SessionDep,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> AuthService:
    return AuthService(
        users=SqlUserRepository(session),
        hasher=request.app.state.hasher,
        tokens=tokens,
        dummy_hash=request.app.state.dummy_hash,
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


def get_export_service(request: Request) -> ExportService:
    # Manages its own transactions: the export row must be committed before
    # the job is published, not at the end of the request.
    state = request.app.state
    return ExportService(
        uow=sql_unit_of_work(state.session_factory),
        queue=state.export_queue,
        files=state.export_files,
        clock=utc_now,
    )


ExportServiceDep = Annotated[ExportService, Depends(get_export_service)]
