"""In-memory adapters that satisfy the application ports, for unit tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.application.ports import TaskQuery
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

    def list(self, query: TaskQuery) -> tuple[list[Task], int]:
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
        rows.sort(key=lambda t: (t.due_date is None, t.due_date, t.id))
        start = (query.page - 1) * query.page_size
        return [replace(t) for t in rows[start : start + query.page_size]], len(rows)


class FakePasswordHasher:
    """Reversible stand-in for Argon2; records every verification."""

    def __init__(self) -> None:
        self.verified: list[tuple[str, str]] = []

    def hash(self, password: str) -> str:
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
