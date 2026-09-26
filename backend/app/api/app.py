from fastapi import APIRouter, FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import auth, users


def create_app() -> FastAPI:
    app = FastAPI(
        title="Task Management API",
        version="1.0.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    register_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(auth.router)
    v1.include_router(users.router)
    app.include_router(v1)
    return app
