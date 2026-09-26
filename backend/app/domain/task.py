from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.domain.errors import ValidationError

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


def _require_aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return now


def _clean_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("title_required", "Title is required")
    if len(cleaned) > TITLE_MAX_LENGTH:
        raise ValidationError(
            "title_too_long", f"Title must be at most {TITLE_MAX_LENGTH} characters"
        )
    return cleaned


def _clean_description(description: str) -> str:
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise ValidationError(
            "description_too_long",
            f"Description must be at most {DESCRIPTION_MAX_LENGTH} characters",
        )
    return description


@dataclass
class Task:
    title: str
    description: str
    status: TaskStatus
    creator_id: int
    assignee_id: int | None
    due_date: date | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    id: int | None = None

    @classmethod
    def create(
        cls,
        *,
        title: str,
        description: str,
        creator_id: int,
        assignee_id: int | None,
        due_date: date | None,
        now: datetime,
    ) -> "Task":
        _require_aware(now)
        return cls(
            title=_clean_title(title),
            description=_clean_description(description),
            status=TaskStatus.PENDING,
            creator_id=creator_id,
            assignee_id=assignee_id,
            due_date=due_date,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )

    def rename(self, title: str, *, now: datetime) -> None:
        self.title = _clean_title(title)
        self._touch(now)

    def describe(self, description: str, *, now: datetime) -> None:
        self.description = _clean_description(description)
        self._touch(now)

    def set_due_date(self, due_date: date | None, *, now: datetime) -> None:
        self.due_date = due_date
        self._touch(now)

    def assign(self, assignee_id: int | None, *, now: datetime) -> None:
        self.assignee_id = assignee_id
        self._touch(now)

    def change_status(self, status: TaskStatus, *, now: datetime) -> None:
        _require_aware(now)
        if status is TaskStatus.COMPLETED:
            if self.status is not TaskStatus.COMPLETED:
                self.completed_at = now
        else:
            self.completed_at = None
        self.status = status
        self._touch(now)

    def _touch(self, now: datetime) -> None:
        self.updated_at = _require_aware(now)
