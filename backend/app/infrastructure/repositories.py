"""SQLAlchemy implementations of the application ports.

Repositories flush but never commit: the caller owns the transaction. They
return domain dataclasses built from rows, never ORM objects, so callers get
detached copies as the TaskRepository contract requires.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from app.application.ports import TaskQuery, UnitOfWork, UnitOfWorkFactory
from app.domain.export import Export, ExportStatus
from app.domain.task import Task, TaskStatus
from app.domain.user import User
from app.infrastructure.models import ExportRow, TaskRow, UserRow


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC) if value else None


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
        conditions = _conditions(query)
        total = self._session.scalar(
            select(func.count()).select_from(TaskRow).where(*conditions)
        )
        rows = self._session.scalars(
            select(TaskRow)
            .where(*conditions)
            .order_by(*_LISTING_ORDER)
            .limit(query.page_size)
            .offset((query.page - 1) * query.page_size)
        )
        return [_to_task(row) for row in rows], total or 0

    def iter_all(self, query: TaskQuery) -> Iterator[Task]:
        # Streamed in batches (server-side cursor), so memory stays flat for
        # large exports.
        rows = self._session.scalars(
            select(TaskRow)
            .where(*_conditions(query))
            .order_by(*_LISTING_ORDER)
            .execution_options(yield_per=500)
        )
        for row in rows:
            yield _to_task(row)


_LISTING_ORDER = (TaskRow.due_date.asc().nulls_last(), TaskRow.id.asc())


def _conditions(query: TaskQuery) -> list[ColumnElement[bool]]:
    """Visibility (creator or assignee) plus the optional filters."""
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
    return conditions


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


def _to_export(row: ExportRow) -> Export:
    return Export(
        id=row.id,
        requester_id=row.requester_id,
        task_status=TaskStatus(row.task_status) if row.task_status else None,
        due_from=row.due_from,
        due_to=row.due_to,
        status=ExportStatus(row.status),
        created_at=row.created_at.astimezone(UTC),
        dispatched_at=row.dispatched_at.astimezone(UTC),
        finished_at=_utc(row.finished_at),
        row_count=row.row_count,
        expires_at=_utc(row.expires_at),
        error_code=row.error_code,
    )


def _copy_export_into(row: ExportRow, export: Export) -> None:
    row.requester_id = export.requester_id
    row.task_status = export.task_status.value if export.task_status else None
    row.due_from = export.due_from
    row.due_to = export.due_to
    row.status = export.status.value
    row.created_at = export.created_at
    row.dispatched_at = export.dispatched_at
    row.finished_at = export.finished_at
    row.row_count = export.row_count
    row.expires_at = export.expires_at
    row.error_code = export.error_code


class SqlExportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, export: Export) -> Export:
        row = ExportRow()
        _copy_export_into(row, export)
        self._session.add(row)
        self._session.flush()
        return _to_export(row)

    def get(self, export_id: int) -> Export | None:
        row = self._session.get(ExportRow, export_id)
        return _to_export(row) if row else None

    def get_for_update(self, export_id: int) -> Export | None:
        # populate_existing: re-read the locked row even if the session
        # already holds an older copy of it.
        row = self._session.scalar(
            select(ExportRow)
            .where(ExportRow.id == export_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return _to_export(row) if row else None

    def get_many(self, export_ids: list[int]) -> list[Export]:
        if not export_ids:
            return []
        rows = self._session.scalars(
            select(ExportRow).where(ExportRow.id.in_(export_ids))
        )
        return [_to_export(row) for row in rows]

    def claim_stale_pending(
        self, *, dispatched_before: datetime, limit: int
    ) -> list[Export]:
        rows = self._session.scalars(
            select(ExportRow)
            .where(
                ExportRow.status == ExportStatus.PENDING.value,
                ExportRow.dispatched_at < dispatched_before,
            )
            .order_by(ExportRow.dispatched_at, ExportRow.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return [_to_export(row) for row in rows]

    def save(self, export: Export) -> Export:
        if export.id is None:
            raise ValueError("cannot save an export that was never added")
        row = self._session.get_one(ExportRow, export.id)
        _copy_export_into(row, export)
        self._session.flush()
        return _to_export(row)


@dataclass(frozen=True)
class SqlUnitOfWork:
    exports: SqlExportRepository
    tasks: SqlTaskRepository


def sql_unit_of_work(session_factory: Callable[[], Session]) -> UnitOfWorkFactory:
    """Each call opens a session and a transaction around the block."""

    @contextmanager
    def open_transaction() -> Iterator[UnitOfWork]:
        with session_factory() as session, session.begin():
            yield SqlUnitOfWork(
                exports=SqlExportRepository(session), tasks=SqlTaskRepository(session)
            )

    return open_transaction
