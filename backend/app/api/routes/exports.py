from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import FileResponse

from app.api.dependencies import CurrentUser, ExportServiceDep
from app.api.rate_limits import limit_exports
from app.api.routes.tasks import INVALID_RESPONSE
from app.api.schemas import ErrorResponse, ExportCreate, ExportOut
from app.application.tasks import TaskListFilters

router = APIRouter(
    prefix="/exports",
    tags=["exports"],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Missing or not yours"},
    },
)

Responses = dict[int | str, dict[str, Any]]


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ExportOut,
    dependencies=[Depends(limit_exports)],
    responses=INVALID_RESPONSE
    | {503: {"model": ErrorResponse, "description": "Export queue unavailable"}},
    summary="Request a CSV export of the caller's tasks",
    description=(
        "Accepts the listing filters (without paging). The export runs in the "
        "background: poll `GET /exports/{id}` until `status` is `completed`, "
        "then download it from `download_url`."
    ),
)
def request_export(
    body: ExportCreate, user: CurrentUser, service: ExportServiceDep, response: Response
) -> ExportOut:
    export = service.request(user.id, TaskListFilters(**body.model_dump()))
    response.headers["Location"] = f"/api/v1/exports/{export.id}"
    return ExportOut.from_export(export)


@router.get(
    "/{export_id}",
    response_model=ExportOut,
    summary="Export progress (requester only)",
)
def read_export(
    export_id: int, user: CurrentUser, service: ExportServiceDep
) -> ExportOut:
    return ExportOut.from_export(service.get(user.id, export_id))


@router.get(
    "/{export_id}/download",
    response_class=FileResponse,
    responses={
        200: {"content": {"text/csv": {}}, "description": "The CSV file"},
        409: {"model": ErrorResponse, "description": "Still running or failed"},
        410: {"model": ErrorResponse, "description": "Expired or file removed"},
    },
    summary="Download a completed export (requester only)",
)
def download_export(
    export_id: int, user: CurrentUser, service: ExportServiceDep
) -> FileResponse:
    path = service.download(user.id, export_id)
    return FileResponse(
        path,
        media_type="text/csv; charset=utf-8",
        filename=f"tasks-export-{export_id}.csv",
        headers={"Cache-Control": "no-store"},
    )
