"""FastAPI glue for rate limiting: login per client IP, the rest of /api/v1
per authenticated user (falling back to IP for missing or invalid tokens, so
rotating junk tokens does not yield fresh counters)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

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
    decision = limiter.hit(limit, key)
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
