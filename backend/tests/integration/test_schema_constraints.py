from datetime import UTC, datetime

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
                "WHERE c.contype = 'c' AND t.relname IN ('users', 'tasks')"
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
