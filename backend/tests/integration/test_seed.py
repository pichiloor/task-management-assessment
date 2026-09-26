from datetime import date, timedelta

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domain.task import TaskStatus
from app.infrastructure.models import TaskRow, UserRow
from app.infrastructure.repositories import SqlUserRepository
from app.infrastructure.security import Argon2PasswordHasher
from app.infrastructure.seed import (
    DEMO_PASSWORD,
    DEMO_USERS,
    SEED_LOCK_KEY,
    DemoUserConflictError,
    seed_demo_data,
)

TODAY = date(2026, 9, 28)


def seed(session: Session, bulk: int = 0) -> None:
    seed_demo_data(session, Argon2PasswordHasher(), today=TODAY, bulk=bulk)
    session.flush()


def count_tasks(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(TaskRow)) or 0


def demo_user_ids(session: Session) -> list[int]:
    emails = [u.email for u in DEMO_USERS]
    return list(session.scalars(select(UserRow.id).where(UserRow.email.in_(emails))))


def test_demo_users_can_log_in_with_the_published_password(session: Session) -> None:
    seed(session)
    users = SqlUserRepository(session)
    hasher = Argon2PasswordHasher()

    for demo in DEMO_USERS:
        user = users.get_by_email(demo.email)
        assert user is not None and user.is_active
        assert hasher.verify(user.password_hash, DEMO_PASSWORD)


def test_tasks_cover_every_status_and_due_date_case(session: Session) -> None:
    seed(session)
    rows = session.scalars(select(TaskRow)).all()

    assert {r.status for r in rows} == {s.value for s in TaskStatus}
    due = [r.due_date for r in rows]
    assert any(d is None for d in due)
    assert any(d is not None and d < TODAY for d in due)  # overdue
    assert any(d == TODAY for d in due)
    assert any(d is not None and d > TODAY for d in due)
    assert any(r.assignee_id is None for r in rows)
    assert any(r.assignee_id not in (None, r.creator_id) for r in rows)
    for r in rows:
        assert (r.status == "completed") == (r.completed_at is not None)


def test_first_demo_user_sees_more_than_one_page(session: Session) -> None:
    seed(session)
    first = SqlUserRepository(session).get_by_email(DEMO_USERS[0].email)
    assert first is not None

    visible = session.scalar(
        select(func.count())
        .select_from(TaskRow)
        .where((TaskRow.creator_id == first.id) | (TaskRow.assignee_id == first.id))
    )

    assert visible is not None and visible > 20  # default page size


def test_running_twice_changes_nothing(session: Session) -> None:
    seed(session)
    users, tasks = len(demo_user_ids(session)), count_tasks(session)

    seed(session)

    assert (len(demo_user_ids(session)), count_tasks(session)) == (users, tasks)


def test_other_users_and_their_tasks_are_left_alone(session: Session) -> None:
    other = SqlUserRepository(session).create(
        email="real@example.com",
        name="Real",
        password_hash="h",  # pragma: allowlist secret
    )

    seed(session)

    assert session.get_one(UserRow, other.id).name == "Real"
    owned = session.scalar(
        select(func.count()).select_from(TaskRow).where(TaskRow.creator_id == other.id)
    )
    assert owned == 0


@pytest.mark.parametrize("bulk", [0, 250])
def test_bulk_option_adds_exactly_that_many_tasks(session: Session, bulk: int) -> None:
    seed(session)
    base = count_tasks(session)
    session.rollback()  # discard, start again from an empty schema
    assert count_tasks(session) == 0
    assert demo_user_ids(session) == []

    seed(session, bulk=bulk)

    assert count_tasks(session) == base + bulk


@pytest.mark.parametrize("shift", [-400, 0, 30])
def test_due_dates_are_exact_offsets_from_the_given_today(
    session: Session, shift: int
) -> None:
    today = TODAY + timedelta(days=shift)
    seed_demo_data(session, Argon2PasswordHasher(), today=today, bulk=0)
    session.flush()

    def due(title: str) -> date | None:
        return session.scalar(select(TaskRow.due_date).where(TaskRow.title == title))

    assert due("Renew SSL certificate") == today - timedelta(days=1)
    assert due("Update onboarding guide") == today
    assert due("Plan team offsite") == today + timedelta(days=21)
    assert due("Research caching options") is None


def test_bulk_on_an_already_seeded_database_still_adds_tasks(
    session: Session,
) -> None:
    # --bulk is an explicit request (e.g. to measure queries on the dev
    # database), so it must not be skipped just because the demo exists.
    seed(session)
    base = count_tasks(session)

    seed(session, bulk=100)

    assert count_tasks(session) == base + 100


def test_deleted_demo_tasks_are_restored_on_the_next_run(session: Session) -> None:
    seed(session)
    base = count_tasks(session)
    session.execute(
        TaskRow.__table__.delete().where(TaskRow.title == "Plan team offsite")
    )

    seed(session)

    assert count_tasks(session) == base


def test_a_demo_users_own_task_does_not_block_the_demo(session: Session) -> None:
    hashed = Argon2PasswordHasher().hash(DEMO_PASSWORD)
    ana = SqlUserRepository(session).create(
        email=DEMO_USERS[0].email, name="Ana", password_hash=hashed
    )
    session.execute(
        text(
            "INSERT INTO tasks (title, status, creator_id, created_at, updated_at) "
            "VALUES ('Mine', 'pending', :id, now(), now())"
        ),
        {"id": ana.id},
    )

    seed(session)

    titles = set(session.scalars(select(TaskRow.title)))
    assert {"Mine", "Plan team offsite", "Backlog item 01"} <= titles


@pytest.mark.parametrize(
    ("active", "password"),
    [(False, DEMO_PASSWORD), (True, "someone-changed-it")],
)
def test_modified_demo_user_is_reported_not_silently_used(
    session: Session, active: bool, password: str
) -> None:
    hasher = Argon2PasswordHasher()
    SqlUserRepository(session).create(
        email=DEMO_USERS[0].email,
        name="Ana",
        password_hash=hasher.hash(password),
        is_active=active,
    )

    with pytest.raises(DemoUserConflictError) as exc:
        seed_demo_data(session, hasher, today=TODAY)
    assert DEMO_USERS[0].email in str(exc.value)

    seed_demo_data(session, hasher, today=TODAY, reset_users=True)
    session.flush()
    ana = SqlUserRepository(session).get_by_email(DEMO_USERS[0].email)
    assert ana is not None and ana.is_active
    assert hasher.verify(ana.password_hash, DEMO_PASSWORD)


def test_concurrent_runs_are_serialized_by_a_lock(
    engine: Engine, session: Session
) -> None:
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SEED_LOCK_KEY})
        session.execute(text("SET LOCAL lock_timeout = '200ms'"))

        with pytest.raises(OperationalError) as exc:
            seed(session)
        other.rollback()

    assert exc.value.orig is not None
    assert getattr(exc.value.orig, "sqlstate", None) == "55P03"  # lock_not_available
    assert "pg_advisory_xact_lock" in str(exc.value.statement)


def test_the_lock_is_taken_before_anything_is_read_or_written(
    session: Session,
) -> None:
    statements: list[str] = []
    event.listen(
        session.connection(),
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )

    seed(session, bulk=5)

    assert "pg_advisory_xact_lock" in statements[0]


def test_renamed_demo_task_is_recreated_under_its_original_title(
    session: Session,
) -> None:
    # Demo tasks are identified by creator and title: renaming one makes the
    # next run restore the original. Documented behavior, pinned here.
    seed(session)
    base = count_tasks(session)
    session.execute(
        TaskRow.__table__.update()
        .where(TaskRow.title == "Plan team offsite")
        .values(title="Plan team offsite (moved)")
    )

    seed(session)

    assert count_tasks(session) == base + 1


def test_existing_task_check_reads_only_the_demo_keys(session: Session) -> None:
    seed(session, bulk=300)
    fetched: list[int] = []

    def count_rows(conn: object, cursor: object, statement: str, *args: object) -> None:
        if "FROM tasks" in statement and "title" in statement.split("FROM")[0]:
            fetched.append(getattr(cursor, "rowcount", -1))

    event.listen(session.connection(), "after_cursor_execute", count_rows)

    seed(session)

    assert fetched and max(fetched) <= 26
