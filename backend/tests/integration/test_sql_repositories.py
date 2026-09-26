from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Connection, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.ports import TaskQuery
from app.application.tasks import NewTask, TaskChanges, TaskService
from app.domain.errors import ValidationError
from app.domain.task import Task, TaskStatus
from app.infrastructure.repositories import SqlTaskRepository, SqlUserRepository
from tests.fakes import FakeClock

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def insert_user(
    session: Session, email: str, *, name: str = "User", active: bool = True
) -> int:
    return (
        SqlUserRepository(session)
        .create(
            email=email,
            name=name,
            password_hash="hash",  # pragma: allowlist secret
            is_active=active,
        )
        .id
    )


@pytest.fixture
def me(session: Session) -> int:
    return insert_user(session, "me@example.com", name="Me")


@pytest.fixture
def other(session: Session) -> int:
    return insert_user(session, "other@example.com", name="Other")


@pytest.fixture
def tasks(session: Session) -> SqlTaskRepository:
    return SqlTaskRepository(session)


def new_task(creator: int, **overrides: object) -> Task:
    fields: dict[str, object] = {
        "title": "Task",
        "description": "",
        "creator_id": creator,
        "assignee_id": None,
        "due_date": None,
        "now": NOW,
    }
    fields.update(overrides)
    return Task.create(**fields)  # type: ignore[arg-type]


def query(viewer: int, **overrides: object) -> TaskQuery:
    fields: dict[str, object] = {
        "viewer_id": viewer,
        "status": None,
        "due_from": None,
        "due_to": None,
        "page": 1,
        "page_size": 100,
    }
    fields.update(overrides)
    return TaskQuery(**fields)  # type: ignore[arg-type]


class TestTaskRoundTrip:
    def test_all_fields_survive_a_round_trip(
        self, tasks: SqlTaskRepository, me: int, other: int
    ) -> None:
        task = new_task(
            me,
            title="Report",
            description="Details",
            assignee_id=other,
            due_date=date(2026, 10, 1),
        )
        task.change_status(TaskStatus.COMPLETED, now=NOW + timedelta(hours=1))

        stored = tasks.add(task)
        loaded = tasks.get(stored.id or 0)

        assert stored.id is not None
        assert loaded == stored
        # Compare with the original too: a field lost in both directions of
        # the mapping would make `loaded == stored` pass.
        assert replace(loaded, id=None) == task
        assert loaded.status is TaskStatus.COMPLETED
        assert loaded.completed_at == NOW + timedelta(hours=1)
        assert loaded.created_at.tzinfo is not None

    def test_missing_task_returns_none(self, tasks: SqlTaskRepository) -> None:
        assert tasks.get(999_999) is None

    def test_save_updates_and_delete_removes(
        self, tasks: SqlTaskRepository, me: int
    ) -> None:
        task = tasks.add(new_task(me))
        task.rename("Renamed", now=NOW + timedelta(minutes=1))

        tasks.save(task)
        assert tasks.get(task.id or 0).title == "Renamed"  # type: ignore[union-attr]

        tasks.delete(task.id or 0)
        assert tasks.get(task.id or 0) is None

    def test_returned_tasks_are_detached_copies(
        self, tasks: SqlTaskRepository, session: Session, me: int
    ) -> None:
        task = tasks.add(new_task(me))
        loaded = tasks.get(task.id or 0)
        assert loaded is not None

        loaded.rename("Not saved", now=NOW)
        session.flush()
        session.expire_all()

        assert tasks.get(task.id or 0).title == "Task"  # type: ignore[union-attr]


def test_repositories_never_commit(session: Session, me: int) -> None:
    commits: list[object] = []
    event.listen(session, "after_commit", commits.append)
    tasks = SqlTaskRepository(session)

    users = SqlUserRepository(session)

    task = tasks.add(new_task(me))
    tasks.get(task.id or 0)
    tasks.get(999_999)
    task.rename("Renamed", now=NOW)
    tasks.save(task)
    tasks.list(query(me, status=TaskStatus.PENDING, due_from=date(2026, 1, 1)))
    tasks.delete(task.id or 0)
    tasks.delete(999_999)
    users.create(
        email="x@example.com",
        name="X",
        password_hash="h",  # pragma: allowlist secret
    )
    users.get(me)
    users.get(999_999)
    users.get_by_email("x@example.com")
    users.list_active()

    assert commits == []


class TestVisibilityAndFilters:
    def test_lists_only_created_or_assigned(
        self, tasks: SqlTaskRepository, me: int, other: int
    ) -> None:
        mine = tasks.add(new_task(me)).id
        assigned = tasks.add(new_task(other, assignee_id=me)).id
        tasks.add(new_task(other))

        items, total = tasks.list(query(me))

        assert [t.id for t in items] == [mine, assigned]
        assert total == 2

    def test_status_and_date_range_combine(
        self, tasks: SqlTaskRepository, me: int
    ) -> None:
        match = new_task(me, due_date=date(2026, 9, 15))
        match.change_status(TaskStatus.IN_PROGRESS, now=NOW)
        match_id = tasks.add(match).id
        tasks.add(new_task(me, due_date=date(2026, 9, 15)))
        wrong_date = new_task(me, due_date=date(2026, 10, 15))
        wrong_date.change_status(TaskStatus.IN_PROGRESS, now=NOW)
        tasks.add(wrong_date)

        items, total = tasks.list(
            query(
                me,
                status=TaskStatus.IN_PROGRESS,
                due_from=date(2026, 9, 1),
                due_to=date(2026, 9, 30),
            )
        )

        assert [t.id for t in items] == [match_id]
        assert total == 1

    def test_open_ranges_exclude_tasks_without_due_date(
        self, tasks: SqlTaskRepository, me: int
    ) -> None:
        early = tasks.add(new_task(me, due_date=date(2026, 9, 1))).id
        late = tasks.add(new_task(me, due_date=date(2026, 12, 1))).id
        tasks.add(new_task(me))

        from_only, _ = tasks.list(query(me, due_from=date(2026, 10, 1)))
        to_only, _ = tasks.list(query(me, due_to=date(2026, 10, 1)))

        assert [t.id for t in from_only] == [late]
        assert [t.id for t in to_only] == [early]


class TestOrderingAndPagination:
    def test_due_date_ascending_nulls_last_then_id(
        self, tasks: SqlTaskRepository, me: int
    ) -> None:
        no_date = tasks.add(new_task(me)).id
        late = tasks.add(new_task(me, due_date=date(2026, 12, 1))).id
        tie_a = tasks.add(new_task(me, due_date=date(2026, 10, 1))).id
        tie_b = tasks.add(new_task(me, due_date=date(2026, 10, 1))).id
        early = tasks.add(new_task(me, due_date=date(2026, 9, 1))).id

        items, _ = tasks.list(query(me))

        assert [t.id for t in items] == [early, tie_a, tie_b, late, no_date]

    def test_pages_are_disjoint_and_total_is_global(
        self, tasks: SqlTaskRepository, me: int
    ) -> None:
        ids = [
            tasks.add(new_task(me, due_date=date(2026, 10, 1 + i % 3))).id
            for i in range(7)
        ]

        pages = [tasks.list(query(me, page=n, page_size=3)) for n in (1, 2, 3, 4)]

        seen = [t.id for items, _ in pages for t in items]
        assert sorted(seen) == sorted(ids)
        assert [len(items) for items, _ in pages] == [3, 3, 1, 0]
        assert {total for _, total in pages} == {7}


class TestUsers:
    def test_get_and_list_active(self, session: Session) -> None:
        users = SqlUserRepository(session)
        active = insert_user(session, "a@example.com", name="Active")
        insert_user(session, "b@example.com", active=False)

        assert users.get(active).name == "Active"  # type: ignore[union-attr]
        assert users.get(999_999) is None
        assert [u.id for u in users.list_active()] == [active]

    def test_email_lookup_is_case_insensitive(self, session: Session) -> None:
        user_id = insert_user(session, "Mixed@Example.com")

        found = SqlUserRepository(session).get_by_email("mixed@EXAMPLE.com")

        assert found is not None and found.id == user_id
        assert found.email == "mixed@example.com"

    def test_email_is_unique_ignoring_case(self, session: Session) -> None:
        insert_user(session, "dup@example.com")
        with pytest.raises(IntegrityError):
            insert_user(session, "DUP@example.com")


class TestConstraints:
    def test_unknown_status_is_rejected_by_the_database(
        self, connection: Connection, tasks: SqlTaskRepository, me: int
    ) -> None:
        task_id = tasks.add(new_task(me)).id
        with pytest.raises(IntegrityError):
            connection.execute(
                text("UPDATE tasks SET status = 'archived' WHERE id = :id"),
                {"id": task_id},
            )

    def test_listing_columns_are_indexed(self, connection: Connection) -> None:
        rows = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = 'tasks'")
        ).scalars()
        definitions = " ".join(rows)

        assert "(status, due_date)" in definitions
        assert "(assignee_id)" in definitions
        assert "(creator_id)" in definitions


def test_failed_patch_persists_nothing_with_sql_repositories(
    session: Session, me: int
) -> None:
    service = TaskService(
        tasks=SqlTaskRepository(session),
        users=SqlUserRepository(session),
        clock=FakeClock(),
    )
    task = service.create(me, NewTask(title="Original"))

    with pytest.raises(ValidationError):
        service.update(
            me, task.id or 0, TaskChanges(title="Changed", assignee_id=999_999)
        )
    session.flush()
    session.expire_all()

    assert service.get(me, task.id or 0).title == "Original"
