"""Demo data for local review. The credentials are public on purpose (the
assessment asks for demo credentials) and must never be used outside a local
environment.

Runs only with SEED_DEMO_DATA=true (set by the local Compose `migrate`
service). Idempotent and serialized by an advisory lock: missing demo users
are created, missing demo tasks (matched by creator and title) are recreated,
and nothing else is touched. A demo user that was deactivated or whose
password changed stops the run unless --reset-demo-users is given. `--bulk N`
always adds N random tasks. Due dates are relative to the day each task is
first created (Ecuador calendar date), so they age like real tasks.

    python -m app.infrastructure.seed                 # demo users and tasks
    python -m app.infrastructure.seed --bulk 5000     # plus N random tasks
    python -m app.infrastructure.seed --reset-demo-users
"""

import argparse
import os
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import create_engine, func, insert, select, tuple_
from sqlalchemy.orm import Session

from app.application.ports import PasswordHasher
from app.domain.task import Task, TaskStatus
from app.infrastructure.models import TaskRow, UserRow
from app.infrastructure.repositories import SqlTaskRepository, SqlUserRepository
from app.infrastructure.security import Argon2PasswordHasher
from app.infrastructure.settings import DatabaseSettings

DEMO_PASSWORD = "demo-password-2026"  # pragma: allowlist secret
SEED_LOCK_KEY = 7_302_026  # arbitrary, app-wide advisory lock id
ECUADOR = timezone(timedelta(hours=-5), "America/Guayaquil")


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


class DemoUserConflictError(RuntimeError):
    """A demo account exists but is inactive or no longer has the published
    password. Re-run with --reset-demo-users to restore it."""


def _ensure_users(
    session: Session, hasher: PasswordHasher, *, reset: bool
) -> list[int]:
    users = SqlUserRepository(session)
    ids = []
    for demo in DEMO_USERS:
        existing = users.get_by_email(demo.email)
        if existing is None:
            existing = users.create(
                email=demo.email,
                name=demo.name,
                password_hash=hasher.hash(DEMO_PASSWORD),
            )
        elif not existing.is_active or not hasher.verify(
            existing.password_hash, DEMO_PASSWORD
        ):
            if not reset:
                raise DemoUserConflictError(
                    f"{demo.email} exists but is inactive or its password changed; "
                    "the published demo credentials would not work. Re-run with "
                    "--reset-demo-users to restore it."
                )
            row = session.get_one(UserRow, existing.id)
            row.is_active = True
            row.password_hash = hasher.hash(DEMO_PASSWORD)
            session.flush()
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
    session: Session,
    hasher: PasswordHasher,
    *,
    today: date,
    bulk: int = 0,
    reset_users: bool = False,
) -> int:
    """Returns how many curated demo tasks were (re)created by this call."""
    # Serializes concurrent runs (e.g. two `migrate` containers): released
    # automatically when the transaction ends.
    session.execute(select(func.pg_advisory_xact_lock(SEED_LOCK_KEY)))
    ids = _ensure_users(session, hasher, reset=reset_users)

    # A curated task is identified by its creator and title: deleted or renamed
    # demo tasks come back, and a user's own task only suppresses a demo task
    # if it has the same creator and title. Only the 26 demo keys are returned,
    # so the rows transferred do not grow with --bulk (the database may still
    # scan more to find them).
    wanted = {(ids[spec.creator], spec.title) for spec in CURATED + BACKLOG}
    existing: set[tuple[int, str]] = {
        (creator_id, title)
        for creator_id, title in session.execute(
            select(TaskRow.creator_id, TaskRow.title)
            .where(tuple_(TaskRow.creator_id, TaskRow.title).in_(wanted))
            .distinct()
        )
    }
    now = datetime.now(UTC)
    tasks = SqlTaskRepository(session)
    created = 0
    for spec in CURATED + BACKLOG:
        if (ids[spec.creator], spec.title) not in existing:
            tasks.add(_build(spec, ids, today, now))
            created += 1
    if bulk:
        session.execute(insert(TaskRow), _bulk_rows(bulk, ids, today, now))
    return created


def demo_today(now: datetime) -> date:
    """Calendar date in continental Ecuador (UTC-5, no daylight saving), where
    the demo is presented. Timestamps stay in UTC; only due dates use this."""
    return now.astimezone(ECUADOR).date()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bulk", type=int, default=0, help="extra random tasks")
    parser.add_argument(
        "--reset-demo-users",
        action="store_true",
        help="reactivate demo users and restore the published password",
    )
    args = parser.parse_args()
    if os.environ.get("SEED_DEMO_DATA") != "true":
        parser.error("refusing to seed: set SEED_DEMO_DATA=true (local demo only)")
    if args.bulk < 0:
        parser.error("--bulk must be 0 or greater")

    engine = create_engine(DatabaseSettings().url)
    with Session(engine) as session, session.begin():
        try:
            created = seed_demo_data(
                session,
                Argon2PasswordHasher(),
                today=demo_today(datetime.now(UTC)),
                bulk=args.bulk,
                reset_users=args.reset_demo_users,
            )
        except DemoUserConflictError as exc:
            parser.exit(1, f"seed: {exc}\n")
    engine.dispose()
    users = ", ".join(u.email for u in DEMO_USERS)
    extra = f" Added {args.bulk} bulk tasks." if args.bulk else ""
    print(
        f"Demo data ready ({created} demo tasks created).{extra} "
        f"Users: {users} (password: {DEMO_PASSWORD})"
    )


if __name__ == "__main__":
    main()
