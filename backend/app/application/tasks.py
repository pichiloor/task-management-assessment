from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
from typing import Final

from app.application.ports import Clock, TaskRepository, UserRepository
from app.domain.errors import ValidationError
from app.domain.permissions import ensure_can_delete, ensure_can_update, ensure_can_view
from app.domain.task import Task, TaskStatus
from app.domain.user import User


class Unset(Enum):
    """Marks a PATCH field the client did not send (as opposed to null)."""

    TOKEN = "UNSET"


UNSET: Final = Unset.TOKEN


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

    def assignable_users(self) -> list[User]:
        return self._users.list_active()

    def _ensure_assignable(self, user_id: int | None) -> None:
        if user_id is None:
            return
        user = self._users.get(user_id)
        if user is None or not user.is_active:
            raise ValidationError(
                "assignee_not_found", "Assignee does not exist or is inactive"
            )
