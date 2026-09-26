"""Celery wiring. Retries run synchronously here through Celery's eager
`apply`; the integration suite runs a real worker against Redis."""

import time
from datetime import timedelta
from typing import Any

import pytest

from app.application.exports import EXPORT_FAILED, ExportRunner, ExportService
from app.application.ports import QueueUnavailableError
from app.application.tasks import TaskListFilters
from app.domain.export import ExportStatus
from app.infrastructure.worker import (
    MAX_RETRIES,
    RUN_EXPORT,
    CeleryExportQueue,
    create_celery,
    create_worker_app,
)
from tests.fakes import FakeClock, FakeExportFiles, FakeExportQueue, FakeUnitOfWork

TTL = timedelta(hours=24)


class FlakyFiles(FakeExportFiles):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def write(self, export_id: int, tasks: Any) -> int:
        if self.failures:
            self.failures -= 1
            self.writes += 1
            raise OSError("volume not mounted yet")
        return super().write(export_id, tasks)


def pending_export(uow: FakeUnitOfWork) -> int:
    service = ExportService(
        uow=uow, queue=FakeExportQueue(), files=FakeExportFiles(), clock=FakeClock()
    )
    return service.request(1, TaskListFilters()).id or 0


def run(uow: FakeUnitOfWork, files: FakeExportFiles, export_id: int) -> None:
    runner = ExportRunner(uow=uow, files=files, clock=FakeClock(), ttl=TTL)
    app = create_worker_app("memory://", lambda: runner)
    app.tasks[RUN_EXPORT].apply(args=[export_id])


def test_task_completes_the_export() -> None:
    uow, files = FakeUnitOfWork(), FakeExportFiles()
    export_id = pending_export(uow)

    run(uow, files, export_id)

    export = uow.exports.get(export_id)
    assert export is not None and export.status is ExportStatus.COMPLETED


def test_transient_failures_are_retried() -> None:
    uow, files = FakeUnitOfWork(), FlakyFiles(failures=MAX_RETRIES)
    export_id = pending_export(uow)

    run(uow, files, export_id)

    export = uow.exports.get(export_id)
    assert export is not None and export.status is ExportStatus.COMPLETED
    assert files.writes == MAX_RETRIES + 1


def test_export_is_marked_failed_when_retries_run_out() -> None:
    uow, files = FakeUnitOfWork(), FlakyFiles(failures=MAX_RETRIES + 1)
    export_id = pending_export(uow)

    run(uow, files, export_id)

    export = uow.exports.get(export_id)
    assert export is not None and export.status is ExportStatus.FAILED
    assert export.error_code == EXPORT_FAILED
    assert files.writes == MAX_RETRIES + 1


def test_configuration_favors_safe_redelivery() -> None:
    conf = create_celery("redis://redis:6379/1").conf

    # A job survives a worker crash (acknowledged only after it finishes) and
    # each worker process takes one job at a time.
    assert conf.task_acks_late and conf.task_reject_on_worker_lost
    assert conf.worker_prefetch_multiplier == 1
    # Status lives in PostgreSQL; no result backend and JSON only.
    assert conf.task_ignore_result
    assert conf.accept_content == ["json"]
    # Publishing gives up quickly so the API can answer 503.
    assert conf.task_publish_retry_policy["max_retries"] <= 3
    assert conf.broker_transport_options["visibility_timeout"] >= 60


class RecordingCelery:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, list[int]]] = []
        self.error = error

    def send_task(self, name: str, args: list[int]) -> None:
        if self.error:
            raise self.error
        self.sent.append((name, args))


def test_queue_publishes_the_export_id() -> None:
    celery = RecordingCelery()

    CeleryExportQueue(celery).publish(42)  # type: ignore[arg-type]

    assert celery.sent == [(RUN_EXPORT, [42])]


def test_unreachable_broker_is_reported_quickly() -> None:
    # Port 1 on localhost refuses connections.
    queue = CeleryExportQueue(create_celery("redis://127.0.0.1:1/0"))
    started = time.monotonic()

    with pytest.raises(QueueUnavailableError):
        queue.publish(1)

    assert time.monotonic() - started < 5


def test_each_app_keeps_its_own_task() -> None:
    # Celery shares tasks with every app created later unless told otherwise;
    # the second app's runner must not replace the first one's.
    first_uow, second_uow = FakeUnitOfWork(), FakeUnitOfWork()
    first_id = pending_export(first_uow)
    first = create_worker_app(
        "memory://",
        lambda: ExportRunner(
            uow=first_uow, files=FakeExportFiles(), clock=FakeClock(), ttl=TTL
        ),
    )
    create_worker_app(
        "memory://",
        lambda: ExportRunner(
            uow=second_uow, files=FakeExportFiles(), clock=FakeClock(), ttl=TTL
        ),
    )

    first.tasks[RUN_EXPORT].apply(args=[first_id])

    export = first_uow.exports.get(first_id)
    assert export is not None and export.status is ExportStatus.COMPLETED
    assert RUN_EXPORT not in create_celery("memory://").tasks
