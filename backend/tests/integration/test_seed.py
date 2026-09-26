from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.task import TaskStatus
from app.infrastructure.models import TaskRow, UserRow
from app.infrastructure.repositories import SqlUserRepository
from app.infrastructure.security import Argon2PasswordHasher
from app.infrastructure.seed import DEMO_PASSWORD, DEMO_USERS, seed_demo_data

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

    seed(session, bulk=bulk)

    assert count_tasks(session) == base + bulk


def test_due_dates_are_relative_to_today(session: Session) -> None:
    seed_demo_data(
        session, Argon2PasswordHasher(), today=TODAY + timedelta(days=30), bulk=0
    )
    session.flush()

    overdue = session.scalar(
        select(func.count())
        .select_from(TaskRow)
        .where(TaskRow.due_date < TODAY + timedelta(days=30))
    )
    assert overdue
