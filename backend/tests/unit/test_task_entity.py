from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.domain.errors import ValidationError
from app.domain.task import (
    DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    Task,
    TaskStatus,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def make_task(**overrides: object) -> Task:
    fields: dict[str, object] = {
        "title": "Write report",
        "description": "",
        "creator_id": 1,
        "assignee_id": None,
        "due_date": None,
        "now": NOW,
    }
    fields.update(overrides)
    return Task.create(**fields)  # type: ignore[arg-type]


class TestCreate:
    def test_new_task_is_pending_with_utc_timestamps(self) -> None:
        task = make_task()

        assert task.status is TaskStatus.PENDING
        assert task.completed_at is None
        assert task.created_at == NOW
        assert task.updated_at == NOW

    def test_title_is_stripped(self) -> None:
        assert make_task(title="  Write report  ").title == "Write report"

    @pytest.mark.parametrize("title", ["", "   ", "\n\t"])
    def test_blank_title_is_rejected(self, title: str) -> None:
        with pytest.raises(ValidationError) as exc:
            make_task(title=title)
        assert exc.value.code == "title_required"

    def test_title_at_max_length_is_accepted(self) -> None:
        assert len(make_task(title="x" * TITLE_MAX_LENGTH).title) == TITLE_MAX_LENGTH

    def test_title_over_max_length_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            make_task(title="x" * (TITLE_MAX_LENGTH + 1))
        assert exc.value.code == "title_too_long"

    def test_description_over_max_length_is_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc:
            make_task(description="x" * (DESCRIPTION_MAX_LENGTH + 1))
        assert exc.value.code == "description_too_long"

    def test_past_due_date_is_allowed_to_represent_overdue_tasks(self) -> None:
        yesterday = NOW.date() - timedelta(days=1)
        assert make_task(due_date=yesterday).due_date == yesterday

    def test_naive_timestamp_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_task(now=datetime(2026, 9, 26, 12, 0))


class TestStatus:
    def test_completing_sets_completed_at(self) -> None:
        task = make_task()
        later = NOW + timedelta(hours=1)

        task.change_status(TaskStatus.COMPLETED, now=later)

        assert task.status is TaskStatus.COMPLETED
        assert task.completed_at == later
        assert task.updated_at == later

    def test_leaving_completed_clears_completed_at(self) -> None:
        task = make_task()
        task.change_status(TaskStatus.COMPLETED, now=NOW)

        task.change_status(TaskStatus.IN_PROGRESS, now=NOW + timedelta(hours=1))

        assert task.status is TaskStatus.IN_PROGRESS
        assert task.completed_at is None

    def test_completing_twice_keeps_original_completed_at(self) -> None:
        task = make_task()
        task.change_status(TaskStatus.COMPLETED, now=NOW)

        task.change_status(TaskStatus.COMPLETED, now=NOW + timedelta(hours=1))

        assert task.completed_at == NOW

    def test_only_three_statuses_exist(self) -> None:
        assert {s.value for s in TaskStatus} == {"pending", "in_progress", "completed"}


class TestEdit:
    def test_rename_validates_and_touches_updated_at(self) -> None:
        task = make_task()
        later = NOW + timedelta(minutes=5)

        task.rename("  New title ", now=later)

        assert task.title == "New title"
        assert task.updated_at == later

    def test_rename_to_blank_is_rejected(self) -> None:
        task = make_task()
        with pytest.raises(ValidationError):
            task.rename("   ", now=NOW)

    def test_due_date_can_be_cleared(self) -> None:
        task = make_task(due_date=date(2026, 10, 1))

        task.set_due_date(None, now=NOW)

        assert task.due_date is None


class TestRejectedCallsLeaveTaskUntouched:
    NAIVE = datetime(2026, 9, 26, 13, 0)

    @pytest.mark.parametrize(
        ("method", "value"),
        [
            ("rename", "Changed"),
            ("describe", "Changed"),
            ("set_due_date", date(2030, 1, 1)),
            ("assign", 99),
            ("change_status", TaskStatus.COMPLETED),
        ],
    )
    def test_naive_timestamp_rejects_without_mutating(
        self, method: str, value: object
    ) -> None:
        task = make_task()
        before = replace(task)

        with pytest.raises(ValueError):
            getattr(task, method)(value, now=self.NAIVE)

        assert task == before


class TestTimestampsAreStoredInUtc:
    def test_other_offsets_are_normalized_to_utc(self) -> None:
        guayaquil = timezone(timedelta(hours=-5))
        local_now = datetime(2026, 9, 26, 7, 0, tzinfo=guayaquil)

        task = make_task(now=local_now)
        task.change_status(TaskStatus.COMPLETED, now=local_now)

        for stamp in (task.created_at, task.updated_at, task.completed_at):
            assert stamp is not None
            assert stamp.tzinfo is UTC
            assert stamp == local_now

    @pytest.mark.parametrize(
        ("method", "value"),
        [
            ("rename", "Changed"),
            ("describe", "Changed"),
            ("set_due_date", date(2030, 1, 1)),
            ("assign", 99),
            ("change_status", TaskStatus.IN_PROGRESS),
        ],
    )
    def test_every_mutator_stores_updated_at_in_utc(
        self, method: str, value: object
    ) -> None:
        local_later = datetime(2026, 9, 26, 8, 0, tzinfo=timezone(timedelta(hours=-5)))
        task = make_task()

        getattr(task, method)(value, now=local_later)

        assert task.updated_at.tzinfo is UTC
        assert task.updated_at == local_later
