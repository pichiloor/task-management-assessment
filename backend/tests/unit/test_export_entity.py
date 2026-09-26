from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.domain.errors import ConflictError, NotFoundError
from app.domain.export import Export, ExportStatus
from app.domain.permissions import ensure_can_access_export
from app.domain.task import TaskStatus

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
TTL = timedelta(hours=24)


def make_export(**overrides: object) -> Export:
    fields: dict[str, object] = {
        "requester_id": 1,
        "task_status": TaskStatus.PENDING,
        "due_from": date(2026, 9, 1),
        "due_to": date(2026, 9, 30),
        "now": NOW,
    }
    fields.update(overrides)
    return Export.request(**fields)  # type: ignore[arg-type]


def test_new_export_is_pending_and_keeps_its_filters() -> None:
    export = make_export()

    assert export.status is ExportStatus.PENDING
    assert export.requester_id == 1
    assert export.task_status is TaskStatus.PENDING
    assert (export.due_from, export.due_to) == (date(2026, 9, 1), date(2026, 9, 30))
    assert export.created_at == NOW
    assert export.finished_at is None
    assert export.row_count is None
    assert export.expires_at is None
    assert export.error_code is None


def test_timestamps_are_normalized_to_utc() -> None:
    local = NOW.astimezone(timezone(timedelta(hours=-5)))

    export = make_export(now=local)

    assert export.created_at == NOW and export.created_at.tzinfo is UTC


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError):
        make_export(now=datetime(2026, 9, 26, 12, 0))


def test_complete_records_the_result_and_expiry() -> None:
    export = make_export()

    export.complete(row_count=7, now=NOW + timedelta(seconds=5), ttl=TTL)

    assert export.status is ExportStatus.COMPLETED
    assert export.row_count == 7
    assert export.finished_at == NOW + timedelta(seconds=5)
    assert export.expires_at == NOW + timedelta(seconds=5) + TTL
    assert export.error_code is None


def test_fail_records_the_error_code() -> None:
    export = make_export()

    export.fail("export_failed", now=NOW + timedelta(seconds=5))

    assert export.status is ExportStatus.FAILED
    assert export.error_code == "export_failed"
    assert export.finished_at == NOW + timedelta(seconds=5)
    assert export.row_count is None and export.expires_at is None


@pytest.mark.parametrize("finish", ["complete", "fail"])
def test_only_pending_exports_can_finish(finish: str) -> None:
    export = make_export()
    export.fail("export_failed", now=NOW)

    with pytest.raises(ConflictError) as exc:
        if finish == "complete":
            export.complete(row_count=1, now=NOW, ttl=TTL)
        else:
            export.fail("export_failed", now=NOW)

    assert exc.value.code == "export_not_pending"
    assert export.error_code == "export_failed"


def test_rejected_completion_changes_nothing() -> None:
    export = make_export()

    with pytest.raises(ValueError):
        export.complete(row_count=-1, now=NOW, ttl=TTL)
    with pytest.raises(ValueError):
        export.complete(row_count=1, now=NOW, ttl=timedelta(0))
    with pytest.raises(ValueError):
        export.complete(row_count=1, now=datetime(2026, 9, 26), ttl=TTL)

    assert export.status is ExportStatus.PENDING
    assert export.finished_at is None


def test_expiry_is_reached_exactly_at_expires_at() -> None:
    export = make_export()
    export.complete(row_count=1, now=NOW, ttl=TTL)

    assert not export.is_expired(NOW + TTL - timedelta(microseconds=1))
    assert export.is_expired(NOW + TTL)


def test_unfinished_exports_never_expire() -> None:
    assert not make_export().is_expired(NOW + timedelta(days=365))


class TestAccess:
    def test_requester_can_access(self) -> None:
        export = make_export(requester_id=1)

        assert ensure_can_access_export(export, 1) is export

    @pytest.mark.parametrize("export", [None, make_export(requester_id=2)])
    def test_missing_and_foreign_exports_look_the_same(
        self, export: Export | None
    ) -> None:
        with pytest.raises(NotFoundError) as exc:
            ensure_can_access_export(export, 1)

        assert exc.value.code == "export_not_found"


def test_new_export_counts_as_dispatched_when_requested() -> None:
    assert make_export().dispatched_at == NOW


def test_redispatch_records_the_time() -> None:
    export = make_export()

    export.mark_dispatched(now=NOW + timedelta(minutes=3))

    assert export.dispatched_at == NOW + timedelta(minutes=3)


def test_finished_exports_are_not_redispatched() -> None:
    export = make_export()
    export.fail("export_failed", now=NOW)

    with pytest.raises(ConflictError):
        export.mark_dispatched(now=NOW)
