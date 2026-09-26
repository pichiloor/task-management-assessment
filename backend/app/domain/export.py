"""A CSV export of the requester's tasks, produced in the background.

The filters are stored with the request and applied, together with the
visibility rules, when the worker runs, not when the export is requested.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from app.domain.errors import ConflictError
from app.domain.task import TaskStatus, to_utc


class ExportStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Export:
    requester_id: int
    task_status: TaskStatus | None
    due_from: date | None
    due_to: date | None
    status: ExportStatus
    created_at: datetime
    # Last time the job was handed to the queue; lost jobs are found by it.
    dispatched_at: datetime
    finished_at: datetime | None = None
    row_count: int | None = None
    expires_at: datetime | None = None
    error_code: str | None = None
    id: int | None = None

    @classmethod
    def request(
        cls,
        *,
        requester_id: int,
        task_status: TaskStatus | None,
        due_from: date | None,
        due_to: date | None,
        now: datetime,
    ) -> "Export":
        now = to_utc(now)
        return cls(
            requester_id=requester_id,
            task_status=task_status,
            due_from=due_from,
            due_to=due_to,
            status=ExportStatus.PENDING,
            created_at=now,
            dispatched_at=now,
        )

    def mark_dispatched(self, *, now: datetime) -> None:
        now = to_utc(now)
        self._ensure_pending()
        self.dispatched_at = now

    def complete(self, *, row_count: int, now: datetime, ttl: timedelta) -> None:
        now = to_utc(now)
        if row_count < 0:
            raise ValueError("row_count must not be negative")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        self._ensure_pending()
        self.status = ExportStatus.COMPLETED
        self.row_count = row_count
        self.finished_at = now
        self.expires_at = now + ttl

    def fail(self, code: str, *, now: datetime) -> None:
        now = to_utc(now)
        self._ensure_pending()
        self.status = ExportStatus.FAILED
        self.error_code = code
        self.finished_at = now

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and to_utc(now) >= self.expires_at

    def _ensure_pending(self) -> None:
        if self.status is not ExportStatus.PENDING:
            raise ConflictError(
                "export_not_pending", f"Export is already {self.status.value}"
            )
