"""The export flow end to end: a real Celery worker (run in a thread by
Celery's test helper) consuming from the Compose Redis, and data committed to
the test database, since the worker uses its own connections."""

import csv
import io
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from celery.contrib.testing.worker import start_worker
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.app import create_app
from app.application.exports import ExportRunner
from app.domain.export import Export, ExportStatus
from app.domain.task import Task
from app.infrastructure.export_files import CsvExportFiles
from app.infrastructure.repositories import (
    SqlExportRepository,
    SqlTaskRepository,
    SqlUserRepository,
    sql_unit_of_work,
)
from app.infrastructure.settings import AuthSettings, ExportSettings, RateLimitSettings
from app.infrastructure.worker import (
    CeleryExportQueue,
    create_celery,
    create_worker_app,
)
from tests.fakes import FakeRedis
from tests.integration.conftest import TEST_JWT_SECRET, token_service

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
TTL = timedelta(hours=24)


def _truncate(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE exports, tasks, users RESTART IDENTITY CASCADE"))


@pytest.fixture
def committed(engine: Engine) -> Iterator[Callable[[], Session]]:
    """Real commits; the tables are emptied before and after the test."""
    _truncate(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    _truncate(engine)


@pytest.fixture
def broker_url() -> str:
    return os.environ["TEST_REDIS_URL"]


def add_task(session: Session, creator: int, **fields: object) -> int:
    values: dict[str, object] = {
        "title": "Task",
        "description": "",
        "creator_id": creator,
        "assignee_id": None,
        "due_date": None,
        "now": NOW,
    }
    values.update(fields)
    task = SqlTaskRepository(session).add(Task.create(**values))  # type: ignore[arg-type]
    assert task.id is not None
    return task.id


def make_runner(factory: Callable[[], Session], directory: Path) -> ExportRunner:
    return ExportRunner(
        uow=sql_unit_of_work(factory),
        files=CsvExportFiles(directory),
        clock=lambda: datetime.now(UTC),
        ttl=TTL,
    )


def test_real_worker_processes_an_export_requested_over_http(
    committed: Callable[[], Session], broker_url: str, tmp_path: Path
) -> None:
    with committed() as session, session.begin():
        users = SqlUserRepository(session)
        ana = users.create(email="ana@example.com", name="Ana", password_hash="h")
        bo = users.create(email="bo@example.com", name="Bo", password_hash="h")
        mine = add_task(session, ana.id, title="+SUM(1)")
        assigned = add_task(session, bo.id, assignee_id=ana.id)
        add_task(session, bo.id, title="Not visible to Ana")

    # A queue of its own, so jobs left by other runs cannot interfere.
    queue_name = f"test-exports-{uuid.uuid4().hex}"
    worker_app = create_worker_app(broker_url, lambda: make_runner(committed, tmp_path))
    publisher = create_celery(broker_url)
    for celery_app in (worker_app, publisher):
        celery_app.conf.task_default_queue = queue_name
    api = create_app(
        auth=AuthSettings(secret=TEST_JWT_SECRET),
        session_factory=committed,
        redis=FakeRedis(),
        rate_limit=RateLimitSettings(storage_uri="memory://"),
        export_queue=CeleryExportQueue(publisher),
        exports=ExportSettings(dir=tmp_path),
    )
    headers = {"Authorization": f"Bearer {token_service().issue(ana.id)}"}

    with (
        start_worker(worker_app, pool="solo", perform_ping_check=False),
        TestClient(api) as client,
    ):
        response = client.post("/api/v1/exports", json={}, headers=headers)
        assert response.status_code == 202, response.text
        export_id = response.json()["id"]

        deadline = time.monotonic() + 20
        status = "pending"
        while status == "pending" and time.monotonic() < deadline:
            time.sleep(0.2)
            status = client.get(f"/api/v1/exports/{export_id}", headers=headers).json()[
                "status"
            ]
        download = client.get(f"/api/v1/exports/{export_id}/download", headers=headers)
    publisher.close()

    assert status == "completed"
    assert download.status_code == 200
    rows = list(csv.reader(io.StringIO(download.content.decode("utf-8-sig"))))
    assert sorted(int(r[0]) for r in rows[1:]) == sorted([mine, assigned])
    assert "'+SUM(1)" in {r[1] for r in rows[1:]}


def test_unreachable_broker_returns_503_and_records_the_failure(
    committed: Callable[[], Session], tmp_path: Path
) -> None:
    with committed() as session, session.begin():
        ana = SqlUserRepository(session).create(
            email="ana@example.com", name="Ana", password_hash="h"
        )
    publisher = create_celery("redis://127.0.0.1:1/0")  # nothing listens there
    api = create_app(
        auth=AuthSettings(secret=TEST_JWT_SECRET),
        session_factory=committed,
        redis=FakeRedis(),
        rate_limit=RateLimitSettings(storage_uri="memory://"),
        export_queue=CeleryExportQueue(publisher),
        exports=ExportSettings(dir=tmp_path),
    )
    headers = {"Authorization": f"Bearer {token_service().issue(ana.id)}"}

    with TestClient(api) as client:
        response = client.post("/api/v1/exports", json={}, headers=headers)

    assert response.status_code == 503
    assert response.json()["code"] == "queue_unavailable"
    with committed() as session:
        (export,) = session.execute(text("SELECT status, error_code FROM exports"))
    assert tuple(export) == ("failed", "queue_unavailable")


def test_a_second_run_waits_for_the_first_and_then_does_nothing(
    committed: Callable[[], Session], tmp_path: Path
) -> None:
    with committed() as session, session.begin():
        ana = SqlUserRepository(session).create(
            email="ana@example.com", name="Ana", password_hash="h"
        )
        export = SqlExportRepository(session).add(
            Export.request(
                requester_id=ana.id,
                task_status=None,
                due_from=None,
                due_to=None,
                now=NOW,
            )
        )
    assert export.id is not None
    result: list[ExportStatus | None] = []

    # The first "worker" holds the row lock and finishes the export.
    with committed() as first, first.begin():
        locked = SqlExportRepository(first).get_for_update(export.id)
        assert locked is not None
        locked.fail("export_failed", now=NOW)
        SqlExportRepository(first).save(locked)

        second = threading.Thread(
            target=lambda: result.append(
                make_runner(committed, tmp_path).run(export.id or 0)
            )
        )
        second.start()
        second.join(timeout=1)
        # Blocked on the lock, not racing ahead.
        assert second.is_alive()

    second.join(timeout=10)
    assert result == [ExportStatus.FAILED]
    assert list(tmp_path.iterdir()) == []
