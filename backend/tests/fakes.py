"""In-memory adapters that satisfy the application ports, for unit tests."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.application.ports import QueueUnavailableError, TaskQuery, TaskSort
from app.domain.export import Export, ExportStatus
from app.domain.task import Task
from app.domain.user import User


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.current = start or datetime(2026, 9, 26, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


class InMemoryUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._users = {u.id: u for u in users or []}

    def get(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        wanted = email.strip().lower()
        return next((u for u in self._users.values() if u.email == wanted), None)

    def list_active(self) -> list[User]:
        return sorted(
            (u for u in self._users.values() if u.is_active), key=lambda u: u.id
        )


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._rows: dict[int, Task] = {}
        self._next_id = 1

    def add(self, task: Task) -> Task:
        stored = replace(task, id=self._next_id)
        self._rows[self._next_id] = stored
        self._next_id += 1
        return replace(stored)

    def get(self, task_id: int) -> Task | None:
        row = self._rows.get(task_id)
        return replace(row) if row else None

    def save(self, task: Task) -> Task:
        assert task.id in self._rows
        self._rows[task.id] = replace(task)
        return replace(task)

    def delete(self, task_id: int) -> None:
        self._rows.pop(task_id, None)

    def _matching(self, query: TaskQuery) -> list[Task]:
        rows = [
            t
            for t in self._rows.values()
            if query.viewer_id in (t.creator_id, t.assignee_id)
            and (query.status is None or t.status is query.status)
            and (
                query.due_from is None or (t.due_date and t.due_date >= query.due_from)
            )
            and (query.due_to is None or (t.due_date and t.due_date <= query.due_to))
        ]
        descending = query.sort.startswith("-")
        if query.sort in (TaskSort.DUE_DATE, TaskSort.DUE_DATE_DESC):
            dated = sorted(
                (t for t in rows if t.due_date is not None),
                key=lambda t: (t.due_date, t.id),
                reverse=descending,
            )
            undated = sorted(
                (t for t in rows if t.due_date is None),
                key=lambda t: t.id,
                reverse=descending,
            )
            return dated + undated
        return sorted(rows, key=lambda t: (t.created_at, t.id), reverse=descending)

    def list(self, query: TaskQuery) -> tuple[list[Task], int]:
        rows = self._matching(query)
        start = (query.page - 1) * query.page_size
        return [replace(t) for t in rows[start : start + query.page_size]], len(rows)

    def iter_all(self, query: TaskQuery) -> Iterator[Task]:
        return (replace(t) for t in self._matching(query))


class FakePasswordHasher:
    """Reversible stand-in for Argon2; records every verification."""

    def __init__(self) -> None:
        self.hashed: list[str] = []
        self.verified: list[tuple[str, str]] = []

    def hash(self, password: str) -> str:
        self.hashed.append(password)
        return "hashed:" + password

    def verify(self, password_hash: str, password: str) -> bool:
        self.verified.append((password_hash, password))
        return password_hash == "hashed:" + password  # pragma: allowlist secret


class FakeTokenService:
    """Tokens are "token:<user id>"; anything else is invalid."""

    def issue(self, user_id: int) -> str:
        return f"token:{user_id}"

    def subject(self, token: str) -> int | None:
        prefix, _, value = token.partition(":")
        return int(value) if prefix == "token" and value.isdigit() else None


class FakeRedis:
    """Answers PING, or fails like an unreachable server."""

    def __init__(self, *, up: bool = True) -> None:
        self.up = up

    def ping(self) -> bool:
        if not self.up:
            raise ConnectionError("redis unavailable")
        return True


class InMemoryExportRepository:
    def __init__(self) -> None:
        self._rows: dict[int, Export] = {}
        self._next_id = 1
        self.locked: list[int] = []
        self.batches: list[int] = []

    def add(self, export: Export) -> Export:
        stored = replace(export, id=self._next_id)
        self._rows[self._next_id] = stored
        self._next_id += 1
        return replace(stored)

    def get(self, export_id: int) -> Export | None:
        row = self._rows.get(export_id)
        return replace(row) if row else None

    def get_for_update(self, export_id: int) -> Export | None:
        self.locked.append(export_id)
        return self.get(export_id)

    def save(self, export: Export) -> Export:
        assert export.id in self._rows
        self._rows[export.id] = replace(export)
        return replace(export)

    def get_many(self, export_ids: list[int]) -> list[Export]:
        self.batches.append(len(export_ids))
        return [replace(self._rows[i]) for i in export_ids if i in self._rows]

    def claim_stale_pending(
        self, *, dispatched_before: datetime, limit: int
    ) -> list[Export]:
        stale = [
            replace(e)
            for e in sorted(self._rows.values(), key=lambda e: e.id or 0)
            if e.status is ExportStatus.PENDING and e.dispatched_at < dispatched_before
        ]
        self.locked.extend(e.id or 0 for e in stale[:limit])
        return stale[:limit]


class FakeUnitOfWork:
    """Calling it opens a "transaction". The in-memory repositories cannot
    roll back, so a test that needs rollback checks `rollbacks` instead."""

    def __init__(self, tasks: InMemoryTaskRepository | None = None) -> None:
        self.tasks = tasks or InMemoryTaskRepository()
        self.exports = InMemoryExportRepository()
        self.commits = 0
        self.rollbacks = 0
        self.broken = False

    @contextmanager
    def __call__(self) -> Iterator["FakeUnitOfWork"]:
        if self.broken:
            raise ConnectionError("database unavailable")
        try:
            yield self
        except BaseException:
            self.rollbacks += 1
            raise
        self.commits += 1


class FakeExportQueue:
    """Records published IDs and how many commits had happened at that time."""

    def __init__(self, uow: FakeUnitOfWork | None = None, *, up: bool = True) -> None:
        self.uow = uow
        self.up = up
        self.published: list[int] = []
        self.commits_at_publish: list[int] = []

    def publish(self, export_id: int) -> None:
        if not self.up:
            raise QueueUnavailableError("broker unavailable")
        self.published.append(export_id)
        if self.uow is not None:
            self.commits_at_publish.append(self.uow.commits)


class FakeExportFiles:
    def __init__(self) -> None:
        self.files: dict[int, list[Task]] = {}
        self.writes = 0
        self.broken = False
        self.temp_cutoffs: list[datetime] = []

    def write(self, export_id: int, tasks: Iterable[Task]) -> int:
        self.writes += 1
        if self.broken:
            raise OSError("disk full")
        self.files[export_id] = list(tasks)
        return len(self.files[export_id])

    def path(self, export_id: int) -> Path | None:
        return Path(f"/exports/{export_id}.csv") if export_id in self.files else None

    def export_ids(self) -> list[int]:
        return sorted(self.files)

    def delete(self, export_id: int) -> None:
        self.files.pop(export_id, None)

    def remove_temp_older_than(self, before: datetime) -> int:
        self.temp_cutoffs.append(before)
        return 0
