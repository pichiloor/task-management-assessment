from datetime import date

import pytest

from app.application.ports import TaskSort
from app.application.tasks import (
    MAX_PAGE_SIZE,
    NewTask,
    TaskChanges,
    TaskListFilters,
    TaskService,
)
from app.domain.errors import ValidationError
from app.domain.task import TaskStatus
from app.domain.user import User
from tests.fakes import FakeClock, InMemoryTaskRepository, InMemoryUserRepository

ME, OTHER = 1, 2


@pytest.fixture
def service() -> TaskService:
    users = InMemoryUserRepository(
        [
            User(
                id=i,
                email=f"u{i}@example.com",
                name=f"U{i}",
                password_hash="x",  # pragma: allowlist secret
                is_active=True,
            )
            for i in (ME, OTHER)
        ]
    )
    return TaskService(tasks=InMemoryTaskRepository(), users=users, clock=FakeClock())


def add(service: TaskService, *, owner: int = ME, due: date | None = None) -> int:
    task = service.create(owner, NewTask(title="t", due_date=due))
    assert task.id is not None
    return task.id


class TestFilters:
    def test_only_own_or_assigned_tasks_are_listed(self, service: TaskService) -> None:
        mine = add(service)
        add(service, owner=OTHER)
        assigned_to_me = service.create(OTHER, NewTask(title="t", assignee_id=ME)).id

        page = service.list(ME, TaskListFilters())

        assert {t.id for t in page.items} == {mine, assigned_to_me}
        assert page.total == 2

    def test_filter_by_status(self, service: TaskService) -> None:
        add(service)
        done = add(service)
        service.update(ME, done, TaskChanges(status=TaskStatus.COMPLETED))

        page = service.list(ME, TaskListFilters(status=TaskStatus.COMPLETED))

        assert [t.id for t in page.items] == [done]

    def test_exact_due_date(self, service: TaskService) -> None:
        add(service, due=date(2026, 9, 27))
        target = add(service, due=date(2026, 9, 28))

        page = service.list(ME, TaskListFilters(due_date=date(2026, 9, 28)))

        assert [t.id for t in page.items] == [target]

    def test_due_range_is_inclusive(self, service: TaskService) -> None:
        add(service, due=date(2026, 9, 1))
        inside = [add(service, due=date(2026, 9, d)) for d in (10, 20)]
        add(service, due=date(2026, 9, 30))

        page = service.list(
            ME, TaskListFilters(due_from=date(2026, 9, 10), due_to=date(2026, 9, 20))
        )

        assert [t.id for t in page.items] == inside

    def test_no_matches_gives_empty_page(self, service: TaskService) -> None:
        add(service)

        page = service.list(ME, TaskListFilters(status=TaskStatus.IN_PROGRESS))

        assert page.items == []
        assert page.total == 0
        assert page.pages == 0

    def test_due_date_cannot_be_combined_with_range(self, service: TaskService) -> None:
        with pytest.raises(ValidationError) as exc:
            service.list(
                ME,
                TaskListFilters(due_date=date(2026, 9, 28), due_from=date(2026, 9, 1)),
            )
        assert exc.value.code == "conflicting_due_filters"

    def test_inverted_range_is_rejected(self, service: TaskService) -> None:
        with pytest.raises(ValidationError) as exc:
            service.list(
                ME,
                TaskListFilters(due_from=date(2026, 9, 30), due_to=date(2026, 9, 1)),
            )
        assert exc.value.code == "invalid_due_range"


class TestPagination:
    def test_page_metadata(self, service: TaskService) -> None:
        for _ in range(5):
            add(service)

        page = service.list(ME, TaskListFilters(page=2, page_size=2))

        assert (page.total, page.page, page.page_size, page.pages) == (5, 2, 2, 3)
        assert len(page.items) == 2

    def test_page_beyond_the_end_is_empty(self, service: TaskService) -> None:
        add(service)

        page = service.list(ME, TaskListFilters(page=3, page_size=20))

        assert page.items == []
        assert page.total == 1

    def test_default_page_size_is_20(self, service: TaskService) -> None:
        assert service.list(ME, TaskListFilters()).page_size == 20

    def test_pages_do_not_overlap_and_cover_everything(
        self, service: TaskService
    ) -> None:
        ids = {add(service, due=date(2026, 10, 1)) for _ in range(7)}

        seen = [
            t.id
            for n in (1, 2, 3)
            for t in service.list(ME, TaskListFilters(page=n, page_size=3)).items
        ]

        assert len(seen) == len(set(seen)) == 7
        assert set(seen) == ids

    @pytest.mark.parametrize(
        ("page", "page_size", "code"),
        [
            (0, 20, "invalid_page"),
            (1, 0, "invalid_page_size"),
            (1, MAX_PAGE_SIZE + 1, "invalid_page_size"),
        ],
    )
    def test_out_of_bounds_values_are_rejected(
        self, service: TaskService, page: int, page_size: int, code: str
    ) -> None:
        with pytest.raises(ValidationError) as exc:
            service.list(ME, TaskListFilters(page=page, page_size=page_size))
        assert exc.value.code == code

    def test_max_page_size_is_accepted(self, service: TaskService) -> None:
        page = service.list(ME, TaskListFilters(page_size=MAX_PAGE_SIZE))
        assert page.page_size == MAX_PAGE_SIZE


class TestSorting:
    def test_default_is_due_date_ascending(self, service: TaskService) -> None:
        late = add(service, due=date(2026, 12, 1))
        early = add(service, due=date(2026, 9, 1))

        page = service.list(ME, TaskListFilters())

        assert [t.id for t in page.items] == [early, late]

    def test_the_requested_sort_reaches_the_repository(
        self, service: TaskService
    ) -> None:
        early = add(service, due=date(2026, 9, 1))
        no_date = add(service)
        late = add(service, due=date(2026, 12, 1))

        by_due_desc = service.list(ME, TaskListFilters(sort=TaskSort.DUE_DATE_DESC))
        newest_first = service.list(ME, TaskListFilters(sort=TaskSort.CREATED_AT_DESC))

        assert [t.id for t in by_due_desc.items] == [late, early, no_date]
        assert [t.id for t in newest_first.items] == [late, no_date, early]
