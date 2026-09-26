import logging
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

Check = Literal["ok", "unavailable"]


def _database(request: Request) -> Check:
    try:
        with request.app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:  # any failure means "unavailable"
        logger.warning("health: database check failed: %s", type(exc).__name__)
        return "unavailable"
    return "ok"


def _redis(request: Request) -> Check:
    try:
        request.app.state.redis.ping()
    except Exception as exc:
        logger.warning("health: redis check failed: %s", type(exc).__name__)
        return "unavailable"
    return "ok"


@router.get(
    "/api/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
    summary="Liveness of the API, PostgreSQL and Redis (no authentication)",
)
def health(request: Request, response: Response) -> HealthResponse:
    database, redis = _database(request), _redis(request)
    if database == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall: Literal["ok", "degraded", "unavailable"] = "unavailable"
    else:
        overall = "ok" if redis == "ok" else "degraded"
    return HealthResponse(status=overall, database=database, redis=redis)
