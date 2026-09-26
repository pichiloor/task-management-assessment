"""Celery wiring for CSV exports: the queue adapter used by the API and the
task run by the worker. The job carries only the export ID; everything else
is read from PostgreSQL when it runs."""

import logging
from collections.abc import Callable
from typing import Any, Final

from celery import Celery
from kombu.exceptions import OperationalError as KombuOperationalError
from redis.exceptions import RedisError

from app.application.exports import ExportRunner
from app.application.ports import QueueUnavailableError

logger = logging.getLogger(__name__)

RUN_EXPORT: Final = "exports.run"
MAX_RETRIES: Final = 3

_PUBLISH_ERRORS = (KombuOperationalError, RedisError, OSError)


def retry_delay(retries: int) -> int:
    """Seconds before the next attempt: 1, 2, 4..."""
    return 1 << retries


def create_celery(broker_url: str) -> Celery:
    app = Celery("task_management", broker=broker_url, set_as_current=False)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        # Export status lives in PostgreSQL, so no result backend is needed.
        task_ignore_result=True,
        # Acknowledge after the job finishes: a worker crash puts it back in
        # the queue (the runner is idempotent), and each process takes one
        # job at a time.
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_transport_options={
            # An unacknowledged job is redelivered after this many seconds.
            "visibility_timeout": 600,
            "socket_connect_timeout": 1,
            "socket_timeout": 5,
        },
        # Publishing from the API gives up after ~1 s so it can answer 503.
        task_publish_retry=True,
        task_publish_retry_policy={
            "max_retries": 2,
            "interval_start": 0,
            "interval_step": 0.5,
            "interval_max": 0.5,
        },
    )
    return app


class CeleryExportQueue:
    def __init__(self, celery: Celery) -> None:
        self._celery = celery

    def publish(self, export_id: int) -> None:
        try:
            self._celery.send_task(RUN_EXPORT, args=[export_id])
        except _PUBLISH_ERRORS as exc:
            raise QueueUnavailableError(type(exc).__name__) from exc


def create_worker_app(broker_url: str, runner: Callable[[], ExportRunner]) -> Celery:
    """`runner` is called inside the worker process, so database connections
    are opened after Celery forks its pool processes."""
    app = create_celery(broker_url)

    def run_export(task: Any, export_id: int) -> None:
        export_runner = runner()
        try:
            status = export_runner.run(export_id)
        except Exception as exc:
            retries: int = task.request.retries
            if retries < MAX_RETRIES:
                logger.warning(
                    "export %s: attempt %s failed (%s), retrying",
                    export_id,
                    retries + 1,
                    type(exc).__name__,
                )
                raise task.retry(exc=exc, countdown=retry_delay(retries)) from exc
            logger.exception("export %s: giving up after %s", export_id, retries + 1)
            export_runner.fail(export_id)
            return
        logger.info("export %s: %s", export_id, status or "not found")

    # shared=False: Celery otherwise registers the task on every app created
    # later in the same process (such as the API's publisher).
    app.task(name=RUN_EXPORT, bind=True, max_retries=MAX_RETRIES, shared=False)(
        run_export
    )
    return app
