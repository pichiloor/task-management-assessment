from datetime import date, timedelta
from pathlib import Path

import pytest

from app.application.exports import (
    EXPORT_FAILED,
    QUEUE_UNAVAILABLE,
    ExportRunner,
    ExportService,
)
from app.application.tasks import TaskListFilters
from app.domain.errors import (
    ConflictError,
    GoneError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.domain.export import Export, ExportStatus
from app.domain.task import Task, TaskStatus
from tests.fakes import FakeClock, FakeExportFiles, FakeExportQueue, FakeUnitOfWork

OWNER, OTHER, OUTSIDER = 1, 2, 3
TTL = timedelta(hours=24)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def queue(uow: FakeUnitOfWork) -> FakeExportQueue:
    return FakeExportQueue(uow)


@pytest.fixture
def files() -> FakeExportFiles:
    return FakeExportFiles()


@pytest.fixture
def service(
    uow: FakeUnitOfWork,
    queue: FakeExportQueue,
    files: FakeExportFiles,
    clock: FakeClock,
) -> ExportService:
    return ExportService(uow=uow, queue=queue, files=files, clock=clock)


@pytest.fixture
def runner(
    uow: FakeUnitOfWork, files: FakeExportFiles, clock: FakeClock
) -> ExportRunner:
    return ExportRunner(uow=uow, files=files, clock=clock, ttl=TTL)


def add_task(uow: FakeUnitOfWork, clock: FakeClock, **overrides: object) -> int:
    fields: dict[str, object] = {
        "title": "Task",
        "description": "",
        "creator_id": OWNER,
        "assignee_id": None,
        "due_date": None,
        "now": clock(),
    }
    fields.update(overrides)
    task = uow.tasks.add(Task.create(**fields))  # type: ignore[arg-type]
    assert task.id is not None
    return task.id


def stored(uow: FakeUnitOfWork, export_id: int | None) -> Export:
    export = uow.exports.get(export_id or 0)
    assert export is not None
    return export


class TestRequest:
    def test_stores_a_pending_export_and_publishes_it_after_commit(
        self, service: ExportService, uow: FakeUnitOfWork, queue: FakeExportQueue
    ) -> None:
        export = service.request(
            OWNER,
            TaskListFilters(status=TaskStatus.PENDING, due_date=date(2026, 9, 30)),
        )

        assert export.id is not None
        assert queue.published == [export.id]
        # The worker must find the row: it was committed before publishing.
        assert queue.commits_at_publish == [1]
        saved = stored(uow, export.id)
        assert saved.status is ExportStatus.PENDING
        assert saved.requester_id == OWNER
        assert saved.task_status is TaskStatus.PENDING
        # An exact due date is stored as a one-day range.
        assert (saved.due_from, saved.due_to) == (date(2026, 9, 30), date(2026, 9, 30))

    @pytest.mark.parametrize(
        ("filters", "code"),
        [
            (
                TaskListFilters(due_from=date(2026, 10, 2), due_to=date(2026, 10, 1)),
                "invalid_due_range",
            ),
            (
                TaskListFilters(due_date=date(2026, 10, 1), due_to=date(2026, 10, 1)),
                "conflicting_due_filters",
            ),
        ],
    )
    def test_invalid_filters_store_and_publish_nothing(
        self,
        service: ExportService,
        uow: FakeUnitOfWork,
        queue: FakeExportQueue,
        filters: TaskListFilters,
        code: str,
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            service.request(OWNER, filters)

        assert exc.value.code == code
        assert uow.exports.get(1) is None
        assert queue.published == []

    def test_unavailable_queue_fails_the_export_and_reports_503(
        self, service: ExportService, uow: FakeUnitOfWork, queue: FakeExportQueue
    ) -> None:
        queue.up = False

        with pytest.raises(ServiceUnavailableError) as exc:
            service.request(OWNER, TaskListFilters())

        assert exc.value.code == QUEUE_UNAVAILABLE
        saved = stored(uow, 1)
        assert saved.status is ExportStatus.FAILED
        assert saved.error_code == QUEUE_UNAVAILABLE

    def test_queue_and_database_both_down_still_reports_503(
        self, service: ExportService, uow: FakeUnitOfWork, queue: FakeExportQueue
    ) -> None:
        queue.up = False

        def breaks_after_first_commit() -> object:
            if uow.commits:
                uow.broken = True
            return uow()

        service = ExportService(
            uow=breaks_after_first_commit,  # type: ignore[arg-type]
            queue=queue,
            files=FakeExportFiles(),
            clock=FakeClock(),
        )

        with pytest.raises(ServiceUnavailableError):
            service.request(OWNER, TaskListFilters())

        # Could not be marked failed; it stays pending (documented limitation).
        assert stored(uow, 1).status is ExportStatus.PENDING


class TestGet:
    def test_requester_sees_the_export(self, service: ExportService) -> None:
        export = service.request(OWNER, TaskListFilters())

        assert service.get(OWNER, export.id or 0) == export

    @pytest.mark.parametrize("actor", [OTHER, OUTSIDER])
    def test_other_users_get_not_found(
        self, service: ExportService, actor: int
    ) -> None:
        export = service.request(OWNER, TaskListFilters())

        with pytest.raises(NotFoundError) as exc:
            service.get(actor, export.id or 0)
        assert exc.value.code == "export_not_found"

    def test_missing_export_gets_not_found(self, service: ExportService) -> None:
        with pytest.raises(NotFoundError):
            service.get(OWNER, 999)


class TestDownload:
    def test_completed_export_returns_its_file(
        self, service: ExportService, runner: ExportRunner
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        runner.run(export_id)

        assert service.download(OWNER, export_id) == Path(f"/exports/{export_id}.csv")

    def test_pending_export_is_not_ready(self, service: ExportService) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0

        with pytest.raises(ConflictError) as exc:
            service.download(OWNER, export_id)
        assert exc.value.code == "export_not_ready"

    def test_failed_export_cannot_be_downloaded(
        self, service: ExportService, runner: ExportRunner
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        runner.fail(export_id)

        with pytest.raises(ConflictError) as exc:
            service.download(OWNER, export_id)
        assert exc.value.code == "export_failed"

    def test_expired_export_is_gone(
        self, service: ExportService, runner: ExportRunner, clock: FakeClock
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        runner.run(export_id)
        clock.advance(hours=24)

        with pytest.raises(GoneError) as exc:
            service.download(OWNER, export_id)
        assert exc.value.code == "export_expired"

    def test_missing_file_is_gone(
        self, service: ExportService, runner: ExportRunner, files: FakeExportFiles
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        runner.run(export_id)
        files.files.clear()

        with pytest.raises(GoneError) as exc:
            service.download(OWNER, export_id)
        assert exc.value.code == "export_file_missing"

    def test_other_users_cannot_download(
        self, service: ExportService, runner: ExportRunner
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        runner.run(export_id)

        with pytest.raises(NotFoundError):
            service.download(OTHER, export_id)


class TestRun:
    def test_writes_only_visible_matching_tasks_in_listing_order(
        self,
        service: ExportService,
        runner: ExportRunner,
        uow: FakeUnitOfWork,
        files: FakeExportFiles,
        clock: FakeClock,
    ) -> None:
        late = add_task(uow, clock, due_date=date(2026, 10, 20))
        early = add_task(
            uow, clock, creator_id=OTHER, assignee_id=OWNER, due_date=date(2026, 10, 5)
        )
        add_task(uow, clock, creator_id=OTHER, due_date=date(2026, 10, 6))  # hidden
        add_task(uow, clock, due_date=date(2026, 11, 30))  # outside the range
        export_id = (
            service.request(
                OWNER,
                TaskListFilters(due_from=date(2026, 10, 1), due_to=date(2026, 10, 31)),
            ).id
            or 0
        )
        clock.advance(seconds=3)

        assert runner.run(export_id) is ExportStatus.COMPLETED

        assert [t.id for t in files.files[export_id]] == [early, late]
        saved = stored(uow, export_id)
        assert saved.status is ExportStatus.COMPLETED
        assert saved.row_count == 2
        assert saved.finished_at == clock()
        assert saved.expires_at == clock() + TTL
        assert export_id in uow.exports.locked

    def test_filters_and_permissions_are_applied_when_the_worker_runs(
        self,
        service: ExportService,
        runner: ExportRunner,
        uow: FakeUnitOfWork,
        files: FakeExportFiles,
        clock: FakeClock,
    ) -> None:
        reassigned = add_task(uow, clock, creator_id=OTHER, assignee_id=OWNER)
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        # Between the request and the run: one task stops being visible and
        # another is created.
        task = uow.tasks.get(reassigned)
        assert task is not None
        task.assign(OUTSIDER, now=clock())
        uow.tasks.save(task)
        created_later = add_task(uow, clock)

        runner.run(export_id)

        assert [t.id for t in files.files[export_id]] == [created_later]

    @pytest.mark.parametrize("finish", ["complete", "fail"])
    def test_finished_exports_are_not_processed_again(
        self,
        service: ExportService,
        runner: ExportRunner,
        uow: FakeUnitOfWork,
        files: FakeExportFiles,
        finish: str,
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        if finish == "complete":
            runner.run(export_id)
        else:
            runner.fail(export_id)
        before = stored(uow, export_id)
        writes = files.writes

        assert runner.run(export_id) is before.status

        assert files.writes == writes
        assert stored(uow, export_id) == before

    def test_missing_export_is_ignored(
        self, runner: ExportRunner, files: FakeExportFiles
    ) -> None:
        assert runner.run(999) is None
        assert files.writes == 0

    def test_write_failure_propagates_and_leaves_the_export_pending(
        self,
        service: ExportService,
        runner: ExportRunner,
        uow: FakeUnitOfWork,
        files: FakeExportFiles,
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        files.broken = True

        with pytest.raises(OSError):
            runner.run(export_id)

        assert uow.rollbacks == 1
        assert stored(uow, export_id).status is ExportStatus.PENDING


class TestFail:
    def test_marks_a_pending_export_as_failed(
        self,
        service: ExportService,
        runner: ExportRunner,
        uow: FakeUnitOfWork,
        clock: FakeClock,
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0

        runner.fail(export_id)

        saved = stored(uow, export_id)
        assert saved.status is ExportStatus.FAILED
        assert saved.error_code == EXPORT_FAILED
        assert saved.finished_at == clock()

    def test_does_not_touch_a_completed_export(
        self, service: ExportService, runner: ExportRunner, uow: FakeUnitOfWork
    ) -> None:
        export_id = service.request(OWNER, TaskListFilters()).id or 0
        runner.run(export_id)
        before = stored(uow, export_id)

        runner.fail(export_id)

        assert stored(uow, export_id) == before

    def test_missing_export_is_ignored(self, runner: ExportRunner) -> None:
        runner.fail(999)
