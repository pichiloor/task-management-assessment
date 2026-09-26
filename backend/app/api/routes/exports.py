import os
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import CurrentUser, ExportServiceDep
from app.api.rate_limits import limit_exports
from app.api.routes.tasks import INVALID_RESPONSE
from app.api.schemas import ErrorResponse, ExportCreate, ExportOut
from app.application.tasks import TaskListFilters
from app.domain.errors import GoneError

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
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/csv": {}}, "description": "The CSV file"},
        409: {"model": ErrorResponse, "description": "Still running or failed"},
        410: {"model": ErrorResponse, "description": "Expired or file removed"},
    },
    summary="Download a completed export (requester only)",
)
def download_export(
    export_id: int, user: CurrentUser, service: ExportServiceDep
) -> StreamingResponse:
    path = service.download(user.id, export_id)
    # Opened before the response starts: maintenance may delete the file at
    # any moment, and an open file keeps streaming after it is unlinked.
    try:
        handle = path.open("rb")
    except FileNotFoundError:
        raise GoneError(
            "export_file_missing", "The export file is not available"
        ) from None
    size = os.fstat(handle.fileno()).st_size

    def chunks() -> Iterator[bytes]:
        with handle:
            while block := handle.read(64 * 1024):
                yield block

    return StreamingResponse(
        chunks(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="tasks-export-{export_id}.csv"'
            ),
            "Content-Length": str(size),
            "Cache-Control": "no-store",
        },
    )
