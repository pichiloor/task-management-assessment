from datetime import UTC, date, datetime

import pytest
from sqlalchemy import CheckConstraint, Connection, text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.models import Base


def _insert_user(connection: Connection) -> int:
    return connection.execute(
        text(
            "INSERT INTO users (email, name, password_hash, is_active) "
            "VALUES ('c@example.com', 'C', 'h', true) RETURNING id"
        )
    ).scalar_one()


def _insert_task(connection: Connection, **values: object) -> None:
    row: dict[str, object] = {
        "title": "t",
        "status": "pending",
        "completed_at": None,
        "now": datetime(2026, 9, 26, tzinfo=UTC),
        "creator_id": _insert_user(connection),
    }
    row.update(values)
    connection.execute(
        text(
            "INSERT INTO tasks (title, status, creator_id, completed_at, "
            "created_at, updated_at) VALUES (:title, :status, :creator_id, "
            ":completed_at, :now, :now)"
        ),
        row,
    )


def test_check_constraint_names_match_the_models(connection: Connection) -> None:
    in_db = set(
        connection.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE c.contype = 'c' AND t.relname IN ('users', 'tasks', 'exports')"
            )
        ).scalars()
    )
    in_models = {
        str(c.name)
        for table in Base.metadata.tables.values()
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }

    assert in_db == in_models


@pytest.mark.parametrize(
    "values",
    [
        {"status": "archived"},
        {"status": "completed", "completed_at": None},
        {"status": "pending", "completed_at": datetime(2026, 9, 26, tzinfo=UTC)},
    ],
)
def test_database_rejects_inconsistent_rows(
    connection: Connection, values: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        _insert_task(connection, **values)


def test_description_defaults_to_empty(connection: Connection) -> None:
    _insert_task(connection)

    assert connection.execute(text("SELECT description FROM tasks")).scalar_one() == ""


def test_uppercase_email_is_rejected_by_the_database(connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO users (email, name, password_hash, is_active) "
                "VALUES ('Up@example.com', 'U', 'h', true)"
            )
        )


def _insert_export(connection: Connection, **values: object) -> None:
    now = datetime(2026, 9, 26, tzinfo=UTC)
    if "requester_id" not in values:
        values["requester_id"] = _insert_user(connection)
    row: dict[str, object] = {
        "status": "pending",
        "task_status": None,
        "due_from": None,
        "due_to": None,
        "row_count": None,
        "error_code": None,
        "created_at": now,
        "dispatched_at": now,
        "finished_at": None,
        "expires_at": None,
    }
    row.update(values)
    connection.execute(
        text(
            "INSERT INTO exports (requester_id, status, task_status, due_from, "
            "due_to, row_count, error_code, created_at, dispatched_at, "
            "finished_at, expires_at) "
            "VALUES (:requester_id, :status, :task_status, :due_from, :due_to, "
            ":row_count, :error_code, :created_at, :dispatched_at, :finished_at, "
            ":expires_at)"
        ),
        row,
    )


_DONE = datetime(2026, 9, 26, 1, tzinfo=UTC)


def test_consistent_export_rows_are_accepted(connection: Connection) -> None:
    requester = _insert_user(connection)
    _insert_export(connection, requester_id=requester)
    _insert_export(
        connection,
        requester_id=requester,
        status="completed",
        row_count=0,
        finished_at=_DONE,
        expires_at=_DONE,
        task_status="in_progress",
        due_from=date(2026, 9, 1),
        due_to=date(2026, 9, 1),
    )
    _insert_export(
        connection,
        requester_id=requester,
        status="failed",
        error_code="export_failed",
        finished_at=_DONE,
    )


@pytest.mark.parametrize(
    "values",
    [
        {"status": "running"},
        {"task_status": "archived"},
        {"finished_at": _DONE},
        {"status": "completed", "row_count": 1, "expires_at": _DONE},
        {"status": "completed", "finished_at": _DONE, "expires_at": _DONE},
        {"status": "completed", "finished_at": _DONE, "row_count": 1},
        {
            "status": "completed",
            "finished_at": _DONE,
            "row_count": -1,
            "expires_at": _DONE,
        },
        {"status": "failed", "finished_at": _DONE},
        {"error_code": "export_failed"},
        {"row_count": 1},
        {"expires_at": _DONE},
        {"status": "failed", "error_code": "x", "finished_at": _DONE, "row_count": 1},
        {"due_from": date(2026, 9, 2), "due_to": date(2026, 9, 1)},
    ],
)
def test_database_rejects_inconsistent_export_rows(
    connection: Connection, values: dict[str, object]
) -> None:
    with pytest.raises(IntegrityError):
        _insert_export(connection, **values)
