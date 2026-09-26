"""Who may see and change a task.

Hidden tasks raise NotFoundError, not PermissionDeniedError, so that probing
IDs reveals nothing about tasks the caller is not part of.
"""

from collections.abc import Iterable

from app.domain.errors import NotFoundError, PermissionDeniedError
from app.domain.task import Task

ASSIGNEE_EDITABLE_FIELDS = frozenset({"status"})


def ensure_can_view(task: Task | None, user_id: int) -> Task:
    if task is None or user_id not in (task.creator_id, task.assignee_id):
        raise NotFoundError("task_not_found", "Task not found")
    return task


def ensure_can_update(task: Task, user_id: int, fields: Iterable[str]) -> None:
    if user_id == task.creator_id:
        return
    forbidden = sorted(set(fields) - ASSIGNEE_EDITABLE_FIELDS)
    if forbidden:
        raise PermissionDeniedError(
            "forbidden_field",
            "Only the task creator can change: " + ", ".join(forbidden),
        )


def ensure_can_delete(task: Task, user_id: int) -> None:
    if user_id != task.creator_id:
        raise PermissionDeniedError(
            "not_task_creator", "Only the task creator can delete it"
        )
