from datetime import date

import pytest

from app.application.tasks import NewTask, TaskChanges, TaskService
from app.domain.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.domain.task import TaskStatus
from app.domain.user import User
from tests.fakes import FakeClock, InMemoryTaskRepository, InMemoryUserRepository

CREATOR, ASSIGNEE, OUTSIDER, INACTIVE = 1, 2, 3, 4


def user(user_id: int, *, active: bool = True) -> User:
    return User(
        id=user_id,
        email=f"user{user_id}@example.com",
        name=f"User {user_id}",
        password_hash="not-used",  # pragma: allowlist secret
        is_active=active,
    )


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(clock: FakeClock) -> TaskService:
    users = InMemoryUserRepository(
        [user(CREATOR), user(ASSIGNEE), user(OUTSIDER), user(INACTIVE, active=False)]
    )
    return TaskService(tasks=InMemoryTaskRepository(), users=users, clock=clock)


def create(service: TaskService, **overrides: object) -> int:
    fields: dict[str, object] = {"title": "Write report", "assignee_id": ASSIGNEE}
    fields.update(overrides)
    task = service.create(CREATOR, NewTask(**fields))  # type: ignore[arg-type]
    assert task.id is not None
    return task.id


class TestCreate:
    def test_creator_is_the_caller(self, service: TaskService) -> None:
        task = service.get(CREATOR, create(service))

        assert task.creator_id == CREATOR
        assert task.assignee_id == ASSIGNEE
        assert task.status is TaskStatus.PENDING

    def test_unassigned_task_is_allowed(self, service: TaskService) -> None:
        assert (
            service.get(CREATOR, create(service, assignee_id=None)).assignee_id is None
        )

    def test_unknown_assignee_is_rejected(self, service: TaskService) -> None:
        with pytest.raises(ValidationError) as exc:
            create(service, assignee_id=999)
        assert exc.value.code == "assignee_not_found"

    def test_inactive_assignee_is_rejected(self, service: TaskService) -> None:
        with pytest.raises(ValidationError) as exc:
            create(service, assignee_id=INACTIVE)
        assert exc.value.code == "assignee_not_found"


class TestVisibility:
    def test_creator_and_assignee_can_read(self, service: TaskService) -> None:
        task_id = create(service)

        assert service.get(CREATOR, task_id).id == task_id
        assert service.get(ASSIGNEE, task_id).id == task_id

    def test_outsider_gets_not_found_instead_of_forbidden(
        self, service: TaskService
    ) -> None:
        task_id = create(service)

        with pytest.raises(NotFoundError) as exc:
            service.get(OUTSIDER, task_id)
        assert exc.value.code == "task_not_found"

    def test_missing_task_is_not_found(self, service: TaskService) -> None:
        with pytest.raises(NotFoundError):
            service.get(CREATOR, 12345)


class TestUpdateByCreator:
    def test_omitted_fields_are_left_untouched(self, service: TaskService) -> None:
        task_id = create(service, description="keep me", due_date=date(2026, 10, 1))

        task = service.update(CREATOR, task_id, TaskChanges(title="Renamed"))

        assert task.title == "Renamed"
        assert task.description == "keep me"
        assert task.due_date == date(2026, 10, 1)
        assert task.assignee_id == ASSIGNEE

    def test_explicit_none_clears_assignee_and_due_date(
        self, service: TaskService
    ) -> None:
        task_id = create(service, due_date=date(2026, 10, 1))

        task = service.update(
            CREATOR, task_id, TaskChanges(assignee_id=None, due_date=None)
        )

        assert task.assignee_id is None
        assert task.due_date is None

    def test_reassign_to_inactive_user_is_rejected(self, service: TaskService) -> None:
        task_id = create(service)

        with pytest.raises(ValidationError):
            service.update(CREATOR, task_id, TaskChanges(assignee_id=INACTIVE))

    def test_changes_are_persisted(
        self, service: TaskService, clock: FakeClock
    ) -> None:
        task_id = create(service)
        clock.advance(hours=1)

        service.update(CREATOR, task_id, TaskChanges(status=TaskStatus.COMPLETED))

        stored = service.get(CREATOR, task_id)
        assert stored.status is TaskStatus.COMPLETED
        assert stored.completed_at == clock()
        assert stored.updated_at == clock()

    def test_invalid_change_is_not_persisted(self, service: TaskService) -> None:
        task_id = create(service)

        with pytest.raises(ValidationError):
            service.update(
                CREATOR, task_id, TaskChanges(status=TaskStatus.COMPLETED, title=" ")
            )

        assert service.get(CREATOR, task_id).status is TaskStatus.PENDING


class TestUpdateByAssignee:
    def test_assignee_can_change_status(self, service: TaskService) -> None:
        task_id = create(service)

        task = service.update(
            ASSIGNEE, task_id, TaskChanges(status=TaskStatus.IN_PROGRESS)
        )

        assert task.status is TaskStatus.IN_PROGRESS

    @pytest.mark.parametrize(
        "changes",
        [
            TaskChanges(title="Hijacked"),
            TaskChanges(description="Hijacked"),
            TaskChanges(due_date=None),
            TaskChanges(assignee_id=OUTSIDER),
        ],
    )
    def test_assignee_cannot_edit_other_fields(
        self, service: TaskService, changes: TaskChanges
    ) -> None:
        task_id = create(service)

        with pytest.raises(PermissionDeniedError) as exc:
            service.update(ASSIGNEE, task_id, changes)
        assert exc.value.code == "forbidden_field"

    def test_combined_patch_is_rejected_as_a_whole(self, service: TaskService) -> None:
        task_id = create(service)

        with pytest.raises(PermissionDeniedError):
            service.update(
                ASSIGNEE,
                task_id,
                TaskChanges(status=TaskStatus.COMPLETED, title="Sneaky"),
            )

        task = service.get(CREATOR, task_id)
        assert task.status is TaskStatus.PENDING
        assert task.title == "Write report"


class TestUpdateByOutsider:
    def test_outsider_gets_not_found(self, service: TaskService) -> None:
        task_id = create(service)

        with pytest.raises(NotFoundError):
            service.update(OUTSIDER, task_id, TaskChanges(status=TaskStatus.COMPLETED))


class TestDelete:
    def test_creator_can_delete(self, service: TaskService) -> None:
        task_id = create(service)

        service.delete(CREATOR, task_id)

        with pytest.raises(NotFoundError):
            service.get(CREATOR, task_id)

    def test_assignee_cannot_delete(self, service: TaskService) -> None:
        task_id = create(service)

        with pytest.raises(PermissionDeniedError) as exc:
            service.delete(ASSIGNEE, task_id)
        assert exc.value.code == "not_task_creator"

    def test_outsider_gets_not_found(self, service: TaskService) -> None:
        task_id = create(service)

        with pytest.raises(NotFoundError):
            service.delete(OUTSIDER, task_id)


def test_assignable_users_are_active_only(service: TaskService) -> None:
    ids = [u.id for u in service.assignable_users()]

    assert ids == [CREATOR, ASSIGNEE, OUTSIDER]
