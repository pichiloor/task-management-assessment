"""SQLAlchemy implementations of the application ports.

Repositories flush but never commit: the caller owns the transaction. They
return domain dataclasses built from rows, never ORM objects, so callers get
detached copies as the TaskRepository contract requires.
"""

from datetime import UTC

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.application.ports import TaskQuery
from app.domain.task import Task, TaskStatus
from app.domain.user import User
from app.infrastructure.models import TaskRow, UserRow


def _to_task(row: TaskRow) -> Task:
    return Task(
        id=row.id,
        title=row.title,
        description=row.description,
        status=TaskStatus(row.status),
        creator_id=row.creator_id,
        assignee_id=row.assignee_id,
        due_date=row.due_date,
        completed_at=row.completed_at.astimezone(UTC) if row.completed_at else None,
        created_at=row.created_at.astimezone(UTC),
        updated_at=row.updated_at.astimezone(UTC),
    )


def _copy_into(row: TaskRow, task: Task) -> None:
    row.title = task.title
    row.description = task.description
    row.status = task.status.value
    row.creator_id = task.creator_id
    row.assignee_id = task.assignee_id
    row.due_date = task.due_date
    row.completed_at = task.completed_at
    row.created_at = task.created_at
    row.updated_at = task.updated_at


def _to_user(row: UserRow) -> User:
    return User(
        id=row.id,
        email=row.email,
        name=row.name,
        password_hash=row.password_hash,
        is_active=row.is_active,
    )


class SqlTaskRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, task: Task) -> Task:
        row = TaskRow()
        _copy_into(row, task)
        self._session.add(row)
        self._session.flush()
        return _to_task(row)

    def get(self, task_id: int) -> Task | None:
        row = self._session.get(TaskRow, task_id)
        return _to_task(row) if row else None

    def save(self, task: Task) -> Task:
        if task.id is None:
            raise ValueError("cannot save a task that was never added")
        row = self._session.get_one(TaskRow, task.id)
        _copy_into(row, task)
        self._session.flush()
        return _to_task(row)

    def delete(self, task_id: int) -> None:
        row = self._session.get(TaskRow, task_id)
        if row is not None:
            self._session.delete(row)
            self._session.flush()

    def list(self, query: TaskQuery) -> tuple[list[Task], int]:
        conditions = [
            or_(
                TaskRow.creator_id == query.viewer_id,
                TaskRow.assignee_id == query.viewer_id,
            )
        ]
        if query.status is not None:
            conditions.append(TaskRow.status == query.status.value)
        if query.due_from is not None:
            conditions.append(TaskRow.due_date >= query.due_from)
        if query.due_to is not None:
            conditions.append(TaskRow.due_date <= query.due_to)

        total = self._session.scalar(
            select(func.count()).select_from(TaskRow).where(*conditions)
        )
        rows = self._session.scalars(
            select(TaskRow)
            .where(*conditions)
            .order_by(TaskRow.due_date.asc().nulls_last(), TaskRow.id.asc())
            .limit(query.page_size)
            .offset((query.page - 1) * query.page_size)
        )
        return [_to_task(row) for row in rows], total or 0


class SqlUserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: int) -> User | None:
        row = self._session.get(UserRow, user_id)
        return _to_user(row) if row else None

    def get_by_email(self, email: str) -> User | None:
        row = self._session.scalar(
            select(UserRow).where(UserRow.email == email.strip().lower())
        )
        return _to_user(row) if row else None

    def list_active(self) -> list[User]:
        rows = self._session.scalars(
            select(UserRow).where(UserRow.is_active).order_by(UserRow.id)
        )
        return [_to_user(row) for row in rows]

    def create(
        self, *, email: str, name: str, password_hash: str, is_active: bool = True
    ) -> User:
        row = UserRow(
            email=email.strip().lower(),
            name=name,
            password_hash=password_hash,
            is_active=is_active,
        )
        self._session.add(row)
        self._session.flush()
        return _to_user(row)
