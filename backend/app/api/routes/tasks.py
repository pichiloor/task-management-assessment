from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from app.api.dependencies import CurrentUser, TaskServiceDep
from app.api.schemas import ErrorResponse, TaskCreate, TaskOut, TaskPage, TaskUpdate
from app.application.tasks import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    NewTask,
    TaskChanges,
    TaskListFilters,
)
from app.domain.task import TaskStatus

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    responses={401: {"model": ErrorResponse, "description": "Not authenticated"}},
)

Responses = dict[int | str, dict[str, Any]]

_NOT_FOUND: Responses = {
    404: {"model": ErrorResponse, "description": "Missing or not visible"}
}
_FORBIDDEN: Responses = {
    403: {"model": ErrorResponse, "description": "Not allowed for this user"}
}
# FastAPI's own 422 (request validation) or a business-rule error.
INVALID_RESPONSE: Responses = {
    422: {
        "description": "Request validation error or business-rule violation",
        "content": {
            "application/json": {
                "schema": {
                    "anyOf": [
                        {"$ref": "#/components/schemas/HTTPValidationError"},
                        {"$ref": "#/components/schemas/ErrorResponse"},
                    ]
                },
                "examples": {
                    "business_rule": {
                        "value": {
                            "detail": "Title is required",
                            "code": "title_required",
                        }
                    }
                },
            }
        },
    }
}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskOut,
    responses=INVALID_RESPONSE,
    summary="Create a task (the caller becomes its creator)",
)
def create_task(
    body: TaskCreate, user: CurrentUser, service: TaskServiceDep, response: Response
) -> TaskOut:
    task = service.create(user.id, NewTask(**body.model_dump()))
    response.headers["Location"] = f"/api/v1/tasks/{task.id}"
    return TaskOut.model_validate(task)


@router.get(
    "",
    response_model=TaskPage,
    responses=INVALID_RESPONSE,
    summary="List tasks the caller created or is assigned to",
    description=(
        "Ordered by due date (tasks without one last), then ID. `due_date` is an "
        "exact match and cannot be combined with `due_from`/`due_to`."
    ),
)
def list_tasks(
    user: CurrentUser,
    service: TaskServiceDep,
    status_: Annotated[TaskStatus | None, Query(alias="status")] = None,
    due_date: date | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> TaskPage:
    result = service.list(
        user.id,
        TaskListFilters(
            status=status_,
            due_date=due_date,
            due_from=due_from,
            due_to=due_to,
            page=page,
            page_size=page_size,
        ),
    )
    return TaskPage(
        items=[TaskOut.model_validate(t) for t in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/{task_id}", response_model=TaskOut, responses=_NOT_FOUND)
def read_task(task_id: int, user: CurrentUser, service: TaskServiceDep) -> TaskOut:
    return TaskOut.model_validate(service.get(user.id, task_id))


@router.patch(
    "/{task_id}",
    response_model=TaskOut,
    responses=_NOT_FOUND | _FORBIDDEN | INVALID_RESPONSE,
    summary="Change some fields (the assignee may only change status)",
)
def update_task(
    task_id: int, body: TaskUpdate, user: CurrentUser, service: TaskServiceDep
) -> TaskOut:
    sent: dict[str, Any] = body.model_dump(include=body.model_fields_set)
    task = service.update(user.id, task_id, TaskChanges(**sent))
    return TaskOut.model_validate(task)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND | _FORBIDDEN,
    summary="Delete a task (creator only)",
)
def delete_task(task_id: int, user: CurrentUser, service: TaskServiceDep) -> None:
    service.delete(user.id, task_id)
