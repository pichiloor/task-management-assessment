from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from fastapi import APIRouter, Depends, FastAPI
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.dependencies import utc_now
from app.api.errors import register_error_handlers
from app.api.rate_limits import (
    RATE_LIMIT_RESPONSE,
    limit_api,
    register_rate_limit_handler,
)
from app.api.routes import auth as auth_routes
from app.api.routes import exports as export_routes
from app.api.routes import health, tasks, users
from app.application.ports import ExportQueue
from app.infrastructure.database import create_database_engine
from app.infrastructure.export_files import CsvExportFiles
from app.infrastructure.rate_limiter import RateLimiter
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import (
    AuthSettings,
    DatabaseSettings,
    ExportSettings,
    QueueSettings,
    RateLimitSettings,
    RedisSettings,
)
from app.infrastructure.worker import CeleryExportQueue, create_celery


class RedisClient(Protocol):
    def ping(self) -> object: ...


def create_app(
    *,
    auth: AuthSettings | None = None,
    session_factory: Callable[[], Session] | None = None,
    redis: RedisClient | None = None,
    rate_limit: RateLimitSettings | None = None,
    export_queue: ExportQueue | None = None,
    exports: ExportSettings | None = None,
) -> FastAPI:
    """Builds the API. Configuration is read and validated here, so a missing
    or weak JWT secret stops the process at startup. Tests pass their own
    settings, session factory, Redis client, rate-limit settings and export
    queue."""
    auth = auth or AuthSettings()
    database = DatabaseSettings() if session_factory is None else None
    rate_limit = rate_limit or RateLimitSettings()
    exports = exports or ExportSettings()
    broker_url = QueueSettings().resolved_broker_url() if export_queue is None else None
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
            if app.state.owned_celery is not None:
                app.state.owned_celery.close()

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
    v1 = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(limit_api)],
        responses=RATE_LIMIT_RESPONSE,
    )
    v1.include_router(auth_routes.router)
    v1.include_router(users.router)
    v1.include_router(tasks.router)
    v1.include_router(export_routes.router)
    app.include_router(v1)
    app.include_router(health.router)

    # Connections are created last, once nothing else can fail, so a failed
    # startup never leaves a pool that the lifespan would not close.
    engine: Engine | None = None
    if database is not None:
        engine = create_database_engine(database.url)
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
    # Creating the Celery app opens no connection; it connects on publish.
    owned_celery = None
    if export_queue is None:
        assert broker_url is not None
        owned_celery = create_celery(broker_url)
        export_queue = CeleryExportQueue(owned_celery)
    app.state.owned_celery = owned_celery
    app.state.export_queue = export_queue
    app.state.export_files = CsvExportFiles(exports.dir)
    app.state.engine = engine
    app.state.owned_redis = owned_redis
    app.state.redis = redis
    app.state.session_factory = session_factory
    app.state.hasher = hasher
    app.state.dummy_hash = dummy_hash
    app.state.tokens = tokens
    return app
