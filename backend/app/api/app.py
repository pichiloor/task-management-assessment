from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import APIRouter, FastAPI
from redis import Redis
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import utc_now
from app.api.errors import register_error_handlers
from app.api.routes import auth as auth_routes
from app.api.routes import health, tasks, users
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import AuthSettings, DatabaseSettings, RedisSettings


class RedisClient(Protocol):
    def ping(self) -> object: ...


def create_app(
    *,
    auth: AuthSettings | None = None,
    session_factory: Callable[[], Session] | None = None,
    redis: RedisClient | None = None,
) -> FastAPI:
    """Builds the API. Configuration is read and validated here, so a missing
    or weak JWT secret stops the process at startup. Tests pass their own
    settings, session factory and Redis client."""
    auth = auth or AuthSettings()
    database = DatabaseSettings() if session_factory is None else None
    redis_url = RedisSettings().url if redis is None else None
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
    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth_routes.router)
    v1.include_router(users.router)
    v1.include_router(tasks.router)
    app.include_router(v1)
    app.include_router(health.router)

    # Connections are created last, once nothing else can fail, so a failed
    # startup never leaves a pool that the lifespan would not close.
    engine: Engine | None = None
    if database is not None:
        engine = create_engine(database.url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    owned_redis: Redis | None = None
    if redis_url is not None:
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
