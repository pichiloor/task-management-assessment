"""CSV exports: requested over HTTP (ExportService), produced by the worker
(ExportRunner) and supervised by a periodic task (ExportMaintenance).

The export row is committed before the job is published, so the worker always
finds it. If publishing fails the export is marked failed and the caller gets
a 503. Jobs can still be lost afterwards (a crash right after the commit, a
broker restart, a retry that could not be published, a worker that could not
record a failure): PostgreSQL is the source of truth, and ExportMaintenance
republishes exports that stay pending, then gives up on them. This is a
polling substitute for a transactional outbox (documented).
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Final

from app.application.ports import (
    Clock,
    ExportFiles,
    ExportQueue,
    QueueUnavailableError,
    TaskQuery,
    UnitOfWorkFactory,
)
from app.application.tasks import MAX_PAGE_SIZE, TaskListFilters, to_task_query
from app.domain.errors import ConflictError, GoneError, ServiceUnavailableError
from app.domain.export import Export, ExportStatus
from app.domain.permissions import ensure_can_access_export

logger = logging.getLogger(__name__)

QUEUE_UNAVAILABLE: Final = "queue_unavailable"
EXPORT_FAILED: Final = "export_failed"
EXPORT_TIMED_OUT: Final = "export_timed_out"

# A pending export not dispatched for this long has probably lost its job.
REDISPATCH_AFTER: Final = timedelta(minutes=2)
# Pending for this long since it was requested: stop trying.
GIVE_UP_AFTER: Final = timedelta(minutes=30)
REDISPATCH_BATCH: Final = 100
# Files are written just before the export is marked completed; the margin
# keeps a file until its export has certainly expired.
FILE_EXPIRY_MARGIN: Final = timedelta(minutes=5)
# A temporary file this old belongs to a write that died.
TEMP_FILE_MAX_AGE: Final = timedelta(hours=1)


def _fail_if_pending(
    uow: UnitOfWorkFactory, export_id: int, code: str, clock: Clock
) -> None:
    with uow() as tx:
        export = tx.exports.get_for_update(export_id)
        if export is not None and export.status is ExportStatus.PENDING:
            export.fail(code, now=clock())
            tx.exports.save(export)


class ExportService:
    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        queue: ExportQueue,
        files: ExportFiles,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._queue = queue
        self._files = files
        self._clock = clock

    def request(self, actor_id: int, filters: TaskListFilters) -> Export:
        query = to_task_query(actor_id, filters)
        with self._uow() as tx:
            export = tx.exports.add(
                Export.request(
                    requester_id=actor_id,
                    task_status=query.status,
                    due_from=query.due_from,
                    due_to=query.due_to,
                    now=self._clock(),
                )
            )
        assert export.id is not None
        try:
            self._queue.publish(export.id)
        except QueueUnavailableError:
            logger.warning("export %s: queue unavailable", export.id)
            try:
                _fail_if_pending(self._uow, export.id, QUEUE_UNAVAILABLE, self._clock)
            except Exception:
                logger.exception("export %s: could not be marked failed", export.id)
            raise ServiceUnavailableError(
                QUEUE_UNAVAILABLE,
                "Exports are temporarily unavailable; try again later",
            ) from None
        return export

    def get(self, actor_id: int, export_id: int) -> Export:
        with self._uow() as tx:
            return ensure_can_access_export(tx.exports.get(export_id), actor_id)

    def download(self, actor_id: int, export_id: int) -> Path:
        export = self.get(actor_id, export_id)
        if export.status is ExportStatus.PENDING:
            raise ConflictError("export_not_ready", "The export is still running")
        if export.status is ExportStatus.FAILED:
            raise ConflictError("export_failed", "The export failed; request a new one")
        if export.is_expired(self._clock()):
            raise GoneError("export_expired", "The export has expired")
        path = self._files.path(export_id)
        if path is None:
            raise GoneError("export_file_missing", "The export file is not available")
        return path


class ExportRunner:
    """Worker side. Safe to run more than once for the same export: the row is
    locked while it is processed, and a finished export is left untouched."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        files: ExportFiles,
        clock: Clock,
        ttl: timedelta,
    ) -> None:
        self._uow = uow
        self._files = files
        self._clock = clock
        self._ttl = ttl

    def run(self, export_id: int) -> ExportStatus | None:
        """Returns the export's final status, or None if it does not exist.
        Errors propagate (and roll back) so the caller can retry."""
        with self._uow() as tx:
            export = tx.exports.get_for_update(export_id)
            if export is None or export.status is not ExportStatus.PENDING:
                return None if export is None else export.status
            query = TaskQuery(
                viewer_id=export.requester_id,
                status=export.task_status,
                due_from=export.due_from,
                due_to=export.due_to,
                page=1,
                page_size=MAX_PAGE_SIZE,
            )
            rows = self._files.write(export_id, tx.tasks.iter_all(query))
            export.complete(row_count=rows, now=self._clock(), ttl=self._ttl)
            tx.exports.save(export)
            return export.status

    def fail(self, export_id: int, code: str = EXPORT_FAILED) -> None:
        """Marks a still-pending export as failed (retries exhausted)."""
        _fail_if_pending(self._uow, export_id, code, self._clock)


class ExportMaintenance:
    """Run periodically (Celery beat)."""

    def __init__(
        self,
        *,
        uow: UnitOfWorkFactory,
        queue: ExportQueue,
        files: ExportFiles,
        clock: Clock,
        ttl: timedelta,
    ) -> None:
        self._uow = uow
        self._queue = queue
        self._files = files
        self._clock = clock
        self._ttl = ttl

    def redispatch_stale(self) -> int:
        """Republishes pending exports whose job may be lost; returns how
        many were published. A duplicate job is harmless (the runner is
        idempotent)."""
        now = self._clock()
        to_publish: list[int] = []
        with self._uow() as tx:
            stale = tx.exports.claim_stale_pending(
                dispatched_before=now - REDISPATCH_AFTER, limit=REDISPATCH_BATCH
            )
            for export in stale:
                if now - export.created_at >= GIVE_UP_AFTER:
                    export.fail(EXPORT_TIMED_OUT, now=now)
                    logger.warning("export %s: gave up, pending too long", export.id)
                else:
                    export.mark_dispatched(now=now)
                    to_publish.append(export.id or 0)
                tx.exports.save(export)
        published = 0
        for export_id in to_publish:
            try:
                self._queue.publish(export_id)
            except QueueUnavailableError:
                # Still pending; the next run tries again.
                logger.warning("export %s: queue unavailable on redispatch", export_id)
                break
            published += 1
        return published

    def remove_expired_files(self) -> int:
        now = self._clock()
        return self._files.remove_older_than(
            files_before=now - self._ttl - FILE_EXPIRY_MARGIN,
            temp_before=now - TEMP_FILE_MAX_AGE,
        )
