"""Maps business errors to HTTP responses: {"detail": ..., "code": ...}.

FastAPI's own 422 validation responses keep their standard shape.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    GoneError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
    ValidationError,
)

_STATUS: dict[type[DomainError], int] = {
    ValidationError: 422,
    NotFoundError: 404,
    PermissionDeniedError: 403,
    AuthenticationError: 401,
    ConflictError: 409,
    GoneError: 410,
    ServiceUnavailableError: 503,
}


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    status = next((code for cls, code in _STATUS.items() if isinstance(exc, cls)), 400)
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        status_code=status,
        content={"detail": exc.detail, "code": exc.code},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
