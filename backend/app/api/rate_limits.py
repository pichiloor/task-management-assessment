"""FastAPI glue for rate limiting: login per client IP, the rest of /api/v1
per authenticated user (falling back to IP for missing or invalid tokens, so
rotating junk tokens does not yield fresh counters)."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorResponse
from app.infrastructure.rate_limiter import RateLimiter


class RateLimitedError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


def _client_ip(request: Request) -> str:
    # ProxyHeadersMiddleware has already replaced this with the forwarded
    # address when the request came through a trusted proxy.
    return request.client.host if request.client else "unknown"


def _user_or_ip(request: Request) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        user_id = request.app.state.tokens.subject(token)
        if user_id is not None:
            return f"user:{user_id}"
    return f"ip:{_client_ip(request)}"


def _enforce(request: Request, limit: str, key: str) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    decision = limiter.hit(limit, f"{request.app.state.limits.key_prefix}:{key}")
    if not decision.allowed:
        raise RateLimitedError(decision.retry_after)


def limit_api(request: Request) -> None:
    _enforce(request, request.app.state.limits.api, f"api:{_user_or_ip(request)}")


def limit_login(request: Request) -> None:
    _enforce(request, request.app.state.limits.login, f"login:{_client_ip(request)}")


async def _rate_limited_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RateLimitedError)
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests", "code": "rate_limited"},
        headers={"Retry-After": str(exc.retry_after)},
    )


def register_rate_limit_handler(app: FastAPI) -> None:
    app.add_exception_handler(RateLimitedError, _rate_limited_handler)


# Documented on every /api/v1 operation: any of them can be rate limited.
RATE_LIMIT_RESPONSE: dict[int | str, dict[str, Any]] = {
    429: {
        "model": ErrorResponse,
        "description": "Too many requests",
        "headers": {
            "Retry-After": {
                "description": "Seconds until the limit resets",
                "schema": {"type": "integer"},
            }
        },
    }
}
