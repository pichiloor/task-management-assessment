"""Interfaces the use cases depend on; infrastructure provides the implementations."""

from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from app.domain.export import Export
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

    def iter_all(self, query: TaskQuery) -> Iterator[Task]:
        """Every matching task in listing order; page and page_size are
        ignored. Must be consumed inside the transaction that produced it."""
        ...


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


class ExportRepository(Protocol):
    def add(self, export: Export) -> Export: ...

    def get(self, export_id: int) -> Export | None: ...

    def get_for_update(self, export_id: int) -> Export | None:
        """Like `get`, but locks the export until the transaction ends, so
        two workers never process the same export at the same time."""
        ...

    def save(self, export: Export) -> Export: ...

    def claim_stale_pending(
        self, *, dispatched_before: datetime, limit: int
    ) -> list[Export]:
        """Pending exports last dispatched before the given time, locked until
        the transaction ends. Exports locked elsewhere (being processed by a
        worker) are skipped, not waited for."""
        ...


class UnitOfWork(Protocol):
    @property
    def exports(self) -> ExportRepository: ...

    @property
    def tasks(self) -> TaskRepository: ...


# Each call opens one transaction: committed when the block exits normally,
# rolled back when it raises.
UnitOfWorkFactory = Callable[[], AbstractContextManager[UnitOfWork]]


class QueueUnavailableError(Exception):
    """The job could not be handed to the queue."""


class ExportQueue(Protocol):
    def publish(self, export_id: int) -> None:
        """Hands the export to a worker; raises QueueUnavailableError."""
        ...


class ExportFiles(Protocol):
    def write(self, export_id: int, tasks: Iterable[Task]) -> int:
        """Writes (or atomically replaces) the export file; returns the row
        count."""
        ...

    def path(self, export_id: int) -> Path | None:
        """The export file, or None if it does not exist."""
        ...

    def remove_older_than(
        self, *, files_before: datetime, temp_before: datetime
    ) -> int:
        """Deletes export files last written before `files_before` and
        leftover temporary files from before `temp_before`; returns how many."""
        ...
