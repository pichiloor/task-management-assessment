from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import utc_now
from app.api.errors import register_error_handlers
from app.api.routes import auth as auth_routes
from app.api.routes import users
from app.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from app.infrastructure.settings import AuthSettings, DatabaseSettings


def create_app(
    *,
    auth: AuthSettings | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> FastAPI:
    """Builds the API. Configuration is read and validated here, so a missing
    or weak JWT secret stops the process at startup. Tests pass their own
    settings and session factory."""
    auth = auth or AuthSettings()
    engine: Engine | None = None
    if session_factory is None:
        engine = create_engine(DatabaseSettings().url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            # Only the engine created here; an injected factory has its owner.
            if app.state.engine is not None:
                app.state.engine.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="Task Management API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    hasher = Argon2PasswordHasher()
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.hasher = hasher
    app.state.dummy_hash = hasher.hash("timing-equalizer")
    app.state.tokens = JwtTokenService(
        secret=auth.jwt_secret.get_secret_value(),
        ttl=auth.access_token_ttl,
        clock=utc_now,
    )
    register_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth_routes.router)
    v1.include_router(users.router)
    app.include_router(v1)
    return app
