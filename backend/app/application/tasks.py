import math
from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
from typing import Final

from app.application.ports import (
    Clock,
    TaskQuery,
    TaskRepository,
    TaskSort,
    UserRepository,
)
from app.domain.errors import ValidationError
from app.domain.permissions import ensure_can_delete, ensure_can_update, ensure_can_view
from app.domain.task import Task, TaskStatus
from app.domain.user import UserSummary


class Unset(Enum):
    """Marks a PATCH field the client did not send (as opposed to null)."""

    TOKEN = "UNSET"


UNSET: Final = Unset.TOKEN

DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100


@dataclass(frozen=True)
class NewTask:
    title: str
    description: str = ""
    assignee_id: int | None = None
    due_date: date | None = None


@dataclass(frozen=True)
class TaskChanges:
    title: str | Unset = UNSET
    description: str | Unset = UNSET
    status: TaskStatus | Unset = UNSET
    assignee_id: int | None | Unset = UNSET
    due_date: date | None | Unset = UNSET

    def provided(self) -> list[str]:
        return [f.name for f in fields(self) if getattr(self, f.name) is not UNSET]


@dataclass(frozen=True)
class TaskListFilters:
    """`due_date` is an exact match and cannot be combined with the range."""

    status: TaskStatus | None = None
    due_date: date | None = None
    due_from: date | None = None
    due_to: date | None = None
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: TaskSort = TaskSort.DUE_DATE


@dataclass(frozen=True)
class Page:
    items: list[Task]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return math.ceil(self.total / self.page_size)


class TaskService:
    def __init__(
        self, *, tasks: TaskRepository, users: UserRepository, clock: Clock
    ) -> None:
        self._tasks = tasks
        self._users = users
        self._clock = clock

    def create(self, actor_id: int, data: NewTask) -> Task:
        self._ensure_assignable(data.assignee_id)
        task = Task.create(
            title=data.title,
            description=data.description,
            creator_id=actor_id,
            assignee_id=data.assignee_id,
            due_date=data.due_date,
            now=self._clock(),
        )
        return self._tasks.add(task)

    def get(self, actor_id: int, task_id: int) -> Task:
        return ensure_can_view(self._tasks.get(task_id), actor_id)

    def update(self, actor_id: int, task_id: int, changes: TaskChanges) -> Task:
        task = self.get(actor_id, task_id)
        ensure_can_update(task, actor_id, changes.provided())

        now = self._clock()
        if not isinstance(changes.title, Unset):
            task.rename(changes.title, now=now)
        if not isinstance(changes.description, Unset):
            task.describe(changes.description, now=now)
        if not isinstance(changes.due_date, Unset):
            task.set_due_date(changes.due_date, now=now)
        if not isinstance(changes.assignee_id, Unset):
            self._ensure_assignable(changes.assignee_id)
            task.assign(changes.assignee_id, now=now)
        if not isinstance(changes.status, Unset):
            task.change_status(changes.status, now=now)
        return self._tasks.save(task)

    def delete(self, actor_id: int, task_id: int) -> None:
        task = self.get(actor_id, task_id)
        ensure_can_delete(task, actor_id)
        self._tasks.delete(task_id)

    def assignable_users(self) -> list[UserSummary]:
        return [UserSummary(id=u.id, name=u.name) for u in self._users.list_active()]

    def _ensure_assignable(self, user_id: int | None) -> None:
        if user_id is None:
            return
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            raise ValidationError(
                "assignee_not_found", "Assignee does not exist or is inactive"
            )

    # Defined last: the method name shadows the builtin `list` in the class body.
    def list(self, actor_id: int, filters: TaskListFilters) -> Page:
        query = to_task_query(actor_id, filters)
        items, total = self._tasks.list(query)
        return Page(
            items=items, total=total, page=query.page, page_size=query.page_size
        )


def to_task_query(viewer_id: int, f: TaskListFilters) -> TaskQuery:
    """Validates listing filters (shared by the listing and CSV exports)."""
    if f.page < 1:
        raise ValidationError("invalid_page", "Page must be 1 or greater")
    if not 1 <= f.page_size <= MAX_PAGE_SIZE:
        raise ValidationError(
            "invalid_page_size", f"Page size must be between 1 and {MAX_PAGE_SIZE}"
        )
    due_from, due_to = f.due_from, f.due_to
    if f.due_date is not None:
        if due_from is not None or due_to is not None:
            raise ValidationError(
                "conflicting_due_filters",
                "Use either due_date or due_from/due_to, not both",
            )
        due_from = due_to = f.due_date
    if due_from is not None and due_to is not None and due_from > due_to:
        raise ValidationError("invalid_due_range", "due_from must not be after due_to")
    return TaskQuery(
        viewer_id=viewer_id,
        status=f.status,
        due_from=due_from,
        due_to=due_to,
        page=f.page,
        page_size=f.page_size,
        sort=f.sort,
    )
