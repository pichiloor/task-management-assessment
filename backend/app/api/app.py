from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import APIRouter, Depends, FastAPI
from redis import Redis
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.dependencies import utc_now
from app.api.errors import register_error_handlers
from app.api.rate_limits import limit_api, register_rate_limit_handler
from app.api.routes import auth as auth_routes
from app.api.routes import health, tasks, users
from app.infrastructure.rate_limiter import RateLimiter
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import (
    AuthSettings,
    DatabaseSettings,
    RateLimitSettings,
    RedisSettings,
)


class RedisClient(Protocol):
    def ping(self) -> object: ...


def create_app(
    *,
    auth: AuthSettings | None = None,
    session_factory: Callable[[], Session] | None = None,
    redis: RedisClient | None = None,
    rate_limit: RateLimitSettings | None = None,
) -> FastAPI:
    """Builds the API. Configuration is read and validated here, so a missing
    or weak JWT secret stops the process at startup. Tests pass their own
    settings, session factory, Redis client and rate-limit settings."""
    auth = auth or AuthSettings()
    database = DatabaseSettings() if session_factory is None else None
    rate_limit = rate_limit or RateLimitSettings()
    needs_redis_url = redis is None or rate_limit.storage_uri is None
    redis_url = RedisSettings().url if needs_redis_url else None
    hasher = Argon2PasswordHasher()
    dummy_hash = hasher.hash("timing-equalizer")
    tokens = JwtTokenService(
        secret=auth.jwt_secret.get_secret_value(),
        ttl=auth.access_token_ttl,
        clock=utc_now,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Only what was created here; injected objects have their owner.
            if app.state.engine is not None:
                app.state.engine.dispose()
            if app.state.owned_redis is not None:
                app.state.owned_redis.close()

    app = FastAPI(
        lifespan=lifespan,
        title="Task Management API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    register_error_handlers(app)
    register_rate_limit_handler(app)
    # Rewrites the client address from X-Forwarded-For, but only for requests
    # coming from these proxies (nginx in Compose).
    app.add_middleware(
        ProxyHeadersMiddleware,
        trusted_hosts=[h.strip() for h in rate_limit.trusted_proxies.split(",")],
    )
    v1 = APIRouter(prefix="/api/v1", dependencies=[Depends(limit_api)])
    v1.include_router(auth_routes.router)
    v1.include_router(users.router)
    v1.include_router(tasks.router)
    app.include_router(v1)
    app.include_router(health.router)

    # Connections are created last, once nothing else can fail, so a failed
    # startup never leaves a pool that the lifespan would not close.
    engine: Engine | None = None
    if database is not None:
        engine = create_engine(
            database.url,
            pool_pre_ping=True,
            pool_timeout=5,  # seconds waiting for a free pooled connection
            connect_args={
                "connect_timeout": 3,  # seconds to establish a connection
                # ms of unacknowledged data before the socket is dropped: a
                # server that stops answering cannot hang a request forever.
                "tcp_user_timeout": 5000,
                # Server-side bounds for slow queries and lock waits. A server
                # that is fully frozen yet still ACKs TCP is not bounded here:
                # psycopg has no client-side per-query timeout (documented).
                "options": "-c statement_timeout=10000 -c lock_timeout=5000",
            },
        )
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage_uri = rate_limit.storage_uri or redis_url
    assert storage_uri is not None
    app.state.limits = rate_limit
    app.state.rate_limiter = RateLimiter(storage_uri)
    owned_redis: Redis | None = None
    if redis is None and redis_url is not None:
        owned_redis = Redis.from_url(
            redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        redis = owned_redis
    app.state.engine = engine
    app.state.owned_redis = owned_redis
    app.state.redis = redis
    app.state.session_factory = session_factory
    app.state.hasher = hasher
    app.state.dummy_hash = dummy_hash
    app.state.tokens = tokens
    return app
