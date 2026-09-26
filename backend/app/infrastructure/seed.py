"""Demo data for local review. The credentials are public on purpose (the
assessment asks for demo credentials) and must never be used outside a local
environment.

Idempotent: users are created only if their email is missing, and the curated
tasks only if no demo user has created any yet. `--bulk N` is an explicit
request and always adds N random tasks, even on an already-seeded database.
Due dates are relative to `today`, so the demo always has overdue, current and
future tasks.

    python -m app.infrastructure.seed            # demo users and tasks
    python -m app.infrastructure.seed --bulk 5000  # plus N random tasks
"""

import argparse
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.orm import Session

from app.application.ports import PasswordHasher
from app.domain.task import Task, TaskStatus
from app.infrastructure.models import TaskRow
from app.infrastructure.repositories import SqlTaskRepository, SqlUserRepository
from app.infrastructure.security import Argon2PasswordHasher
from app.infrastructure.settings import DatabaseSettings

DEMO_PASSWORD = "demo-password-2026"  # pragma: allowlist secret


@dataclass(frozen=True)
class DemoUser:
    email: str
    name: str


DEMO_USERS = (
    DemoUser("ana@example.com", "Ana Torres"),
    DemoUser("bruno@example.com", "Bruno Díaz"),
    DemoUser("carla@example.com", "Carla Mena"),
)

ANA, BRUNO, CARLA = range(3)
P, IP, C = TaskStatus.PENDING, TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED


@dataclass(frozen=True)
class DemoTask:
    creator: int
    assignee: int | None
    title: str
    status: TaskStatus
    due_in_days: int | None
    description: str = ""


CURATED = (
    DemoTask(ANA, BRUNO, "Prepare Q3 budget review", IP, -3, "Numbers from finance."),
    DemoTask(ANA, CARLA, "Update onboarding guide", P, 0),
    DemoTask(ANA, None, "Plan team offsite", P, 21),
    DemoTask(ANA, BRUNO, "Fix login page typo", C, -10),
    DemoTask(ANA, ANA, "Renew SSL certificate", P, -1, "Expired yesterday!"),
    DemoTask(BRUNO, ANA, "Review pull request #42", IP, 1),
    DemoTask(BRUNO, ANA, "Write release notes", P, 7),
    DemoTask(BRUNO, None, "Research caching options", P, None),
    DemoTask(BRUNO, CARLA, "Migrate CI to new runners", C, -5),
    DemoTask(CARLA, ANA, "Customer feedback summary", P, 3),
    DemoTask(CARLA, BRUNO, "Accessibility audit", IP, 14),
    DemoTask(CARLA, None, "Archive old tickets", C, None),
)
# Enough extra tasks for Ana to need a second page at the default size (20).
BACKLOG = tuple(
    DemoTask(ANA, None if i % 3 else CARLA, f"Backlog item {i:02d}", P, 30 + i)
    for i in range(1, 15)
)


def _build(spec: DemoTask, ids: list[int], today: date, now: datetime) -> Task:
    task = Task.create(
        title=spec.title,
        description=spec.description,
        creator_id=ids[spec.creator],
        assignee_id=None if spec.assignee is None else ids[spec.assignee],
        due_date=None
        if spec.due_in_days is None
        else today + timedelta(spec.due_in_days),
        now=now,
    )
    if spec.status is not TaskStatus.PENDING:
        task.change_status(spec.status, now=now)
    return task


def _ensure_users(session: Session, hasher: PasswordHasher) -> list[int]:
    users = SqlUserRepository(session)
    password_hash: str | None = None
    ids = []
    for demo in DEMO_USERS:
        existing = users.get_by_email(demo.email)
        if existing is None:
            password_hash = password_hash or hasher.hash(DEMO_PASSWORD)
            existing = users.create(
                email=demo.email, name=demo.name, password_hash=password_hash
            )
        ids.append(existing.id)
    return ids


def _bulk_rows(
    count: int, ids: list[int], today: date, now: datetime
) -> list[dict[str, object]]:
    rng = random.Random(42)  # deterministic, so measurements are repeatable
    rows: list[dict[str, object]] = []
    for i in range(count):
        spec = DemoTask(
            creator=rng.randrange(len(ids)),
            assignee=rng.choice([None, *range(len(ids))]),
            title=f"Bulk task {i + 1:05d}",
            status=rng.choice(list(TaskStatus)),
            due_in_days=rng.choice([None, *range(-60, 61)]),
        )
        task = _build(spec, ids, today, now)
        rows.append(
            {
                "title": task.title,
                "description": task.description,
                "status": task.status.value,
                "creator_id": task.creator_id,
                "assignee_id": task.assignee_id,
                "due_date": task.due_date,
                "completed_at": task.completed_at,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
        )
    return rows


def seed_demo_data(
    session: Session, hasher: PasswordHasher, *, today: date, bulk: int = 0
) -> bool:
    """Returns True if the curated demo tasks were created by this call."""
    ids = _ensure_users(session, hasher)
    already_seeded = session.scalar(
        select(func.count()).select_from(TaskRow).where(TaskRow.creator_id.in_(ids))
    )
    now = datetime.now(UTC)
    if not already_seeded:
        tasks = SqlTaskRepository(session)
        for spec in CURATED + BACKLOG:
            tasks.add(_build(spec, ids, today, now))
    if bulk:
        session.execute(insert(TaskRow), _bulk_rows(bulk, ids, today, now))
    return not already_seeded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bulk", type=int, default=0, help="extra random tasks")
    args = parser.parse_args()
    if args.bulk < 0:
        parser.error("--bulk must be 0 or greater")

    engine = create_engine(DatabaseSettings().url)
    with Session(engine) as session, session.begin():
        created = seed_demo_data(
            session,
            Argon2PasswordHasher(),
            today=datetime.now(UTC).date(),
            bulk=args.bulk,
        )
    engine.dispose()
    users = ", ".join(u.email for u in DEMO_USERS)
    state = "created" if created else "already present, left unchanged"
    extra = f" Added {args.bulk} bulk tasks." if args.bulk else ""
    print(f"Demo data {state}.{extra} Users: {users} (password: {DEMO_PASSWORD})")


if __name__ == "__main__":
    main()
