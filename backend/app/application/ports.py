"""Interfaces the use cases depend on; infrastructure provides the implementations."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.domain.task import Task, TaskStatus
from app.domain.user import User

Clock = Callable[[], datetime]


@dataclass(frozen=True)
class TaskQuery:
    """Already-validated listing request. Results must be ordered by
    due date (nulls last), then ID, so pages are stable."""

    viewer_id: int
    status: TaskStatus | None
    due_from: date | None
    due_to: date | None
    page: int
    page_size: int


class TaskRepository(Protocol):
    """Returns detached copies: mutating a returned Task changes nothing until
    `save` is called, so a use case that fails midway persists nothing."""

    def add(self, task: Task) -> Task: ...

    def get(self, task_id: int) -> Task | None: ...

    def save(self, task: Task) -> Task: ...

    def delete(self, task_id: int) -> None: ...

    def list(self, query: TaskQuery) -> tuple[list[Task], int]: ...


class UserRepository(Protocol):
    def get(self, user_id: int) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def list_active(self) -> list[User]: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


class TokenService(Protocol):
    def issue(self, user_id: int) -> str: ...

    def subject(self, token: str) -> int | None:
        """User ID of a valid, unexpired token; None otherwise."""
        ...
