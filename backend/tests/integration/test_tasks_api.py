from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.infrastructure.repositories import SqlUserRepository
from tests.integration.conftest import token_service

Headers = dict[str, str]


@pytest.fixture
def make_user(session: Session) -> Callable[[str], tuple[int, Headers]]:
    def make(name: str) -> tuple[int, Headers]:
        user = SqlUserRepository(session).create(
            email=f"{name}@example.com",
            name=name.title(),
            password_hash="unused",  # pragma: allowlist secret
        )
        token = token_service().issue(user.id)
        return user.id, {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def ana(make_user: Callable[[str], tuple[int, Headers]]) -> tuple[int, Headers]:
    return make_user("ana")


@pytest.fixture
def bo(make_user: Callable[[str], tuple[int, Headers]]) -> tuple[int, Headers]:
    return make_user("bo")


@pytest.fixture
def cy(make_user: Callable[[str], tuple[int, Headers]]) -> tuple[int, Headers]:
    return make_user("cy")


def create(client: TestClient, headers: Headers, **body: Any) -> dict[str, Any]:
    response = client.post(
        "/api/v1/tasks", json={"title": "Task", **body}, headers=headers
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


class TestCreate:
    def test_returns_201_and_the_full_task(
        self, client: TestClient, ana: tuple[int, Headers], bo: tuple[int, Headers]
    ) -> None:
        response = client.post(
            "/api/v1/tasks",
            json={
                "title": "  Write report ",
                "description": "Q3",
                "assignee_id": bo[0],
                "due_date": "2026-10-01",
            },
            headers=ana[1],
        )

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Write report"
        assert body["status"] == "pending"
        assert body["creator_id"] == ana[0]
        assert body["assignee_id"] == bo[0]
        assert body["due_date"] == "2026-10-01"
        assert body["completed_at"] is None
        assert body["created_at"].endswith("Z") or "+00:00" in body["created_at"]
        assert response.headers["Location"] == f"/api/v1/tasks/{body['id']}"

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"title": ""},
            {"title": "x" * 201},
            {"title": "ok", "description": "x" * 2001},
            {"title": "ok", "due_date": "not-a-date"},
            {"title": "ok", "unexpected": 1},
        ],
    )
    def test_invalid_bodies_are_422(
        self, client: TestClient, ana: tuple[int, Headers], body: dict[str, Any]
    ) -> None:
        assert (
            client.post("/api/v1/tasks", json=body, headers=ana[1]).status_code == 422
        )

    def test_blank_title_is_a_business_error(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        response = client.post("/api/v1/tasks", json={"title": "   "}, headers=ana[1])

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Title is required",
            "code": "title_required",
        }

    def test_unknown_assignee_is_422_with_code(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        response = client.post(
            "/api/v1/tasks", json={"title": "t", "assignee_id": 999_999}, headers=ana[1]
        )

        assert response.status_code == 422
        assert response.json()["code"] == "assignee_not_found"

    def test_requires_authentication(self, client: TestClient) -> None:
        assert client.post("/api/v1/tasks", json={"title": "t"}).status_code == 401


class TestRead:
    def test_creator_and_assignee_can_read_outsider_gets_404(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        bo: tuple[int, Headers],
        cy: tuple[int, Headers],
    ) -> None:
        task = create(client, ana[1], assignee_id=bo[0])
        url = f"/api/v1/tasks/{task['id']}"

        assert client.get(url, headers=ana[1]).status_code == 200
        assert client.get(url, headers=bo[1]).status_code == 200
        hidden = client.get(url, headers=cy[1])
        assert hidden.status_code == 404
        assert hidden.json() == {"detail": "Task not found", "code": "task_not_found"}

    def test_missing_task_is_404(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        assert client.get("/api/v1/tasks/999999", headers=ana[1]).status_code == 404


class TestList:
    def test_page_format_and_visibility(
        self, client: TestClient, ana: tuple[int, Headers], bo: tuple[int, Headers]
    ) -> None:
        mine = [create(client, ana[1])["id"] for _ in range(3)]
        create(client, bo[1])

        response = client.get("/api/v1/tasks?page=1&page_size=2", headers=ana[1])

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "total", "page", "page_size", "pages"}
        assert (body["total"], body["page"], body["page_size"], body["pages"]) == (
            3,
            1,
            2,
            2,
        )
        assert [t["id"] for t in body["items"]] == mine[:2]

    def test_filters_by_status_and_exact_due_date(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        target = create(client, ana[1], due_date="2026-09-28")
        create(client, ana[1], due_date="2026-09-29")
        client.patch(
            f"/api/v1/tasks/{target['id']}",
            json={"status": "in_progress"},
            headers=ana[1],
        )

        response = client.get(
            "/api/v1/tasks?status=in_progress&due_date=2026-09-28", headers=ana[1]
        )

        assert [t["id"] for t in response.json()["items"]] == [target["id"]]

    def test_date_range(self, client: TestClient, ana: tuple[int, Headers]) -> None:
        inside = create(client, ana[1], due_date="2026-09-15")
        create(client, ana[1], due_date="2026-10-15")

        response = client.get(
            "/api/v1/tasks?due_from=2026-09-01&due_to=2026-09-30", headers=ana[1]
        )

        assert [t["id"] for t in response.json()["items"]] == [inside["id"]]

    @pytest.mark.parametrize(
        ("query", "code"),
        [
            ("due_date=2026-09-28&due_from=2026-09-01", "conflicting_due_filters"),
            ("due_from=2026-09-30&due_to=2026-09-01", "invalid_due_range"),
        ],
    )
    def test_invalid_filter_combinations(
        self, client: TestClient, ana: tuple[int, Headers], query: str, code: str
    ) -> None:
        response = client.get(f"/api/v1/tasks?{query}", headers=ana[1])

        assert response.status_code == 422
        assert response.json()["code"] == code

    @pytest.mark.parametrize(
        "query", ["page=0", "page_size=0", "page_size=101", "status=archived"]
    )
    def test_out_of_range_parameters(
        self, client: TestClient, ana: tuple[int, Headers], query: str
    ) -> None:
        assert client.get(f"/api/v1/tasks?{query}", headers=ana[1]).status_code == 422


class TestPatch:
    def test_omitted_fields_stay_and_null_clears(
        self, client: TestClient, ana: tuple[int, Headers], bo: tuple[int, Headers]
    ) -> None:
        task = create(
            client, ana[1], description="keep", assignee_id=bo[0], due_date="2026-10-01"
        )
        url = f"/api/v1/tasks/{task['id']}"

        renamed = client.patch(url, json={"title": "Renamed"}, headers=ana[1]).json()
        assert (renamed["description"], renamed["assignee_id"]) == ("keep", bo[0])

        cleared = client.patch(
            url, json={"assignee_id": None, "due_date": None}, headers=ana[1]
        )
        assert cleared.status_code == 200
        assert (cleared.json()["assignee_id"], cleared.json()["due_date"]) == (
            None,
            None,
        )

    @pytest.mark.parametrize("field", ["title", "description", "status"])
    def test_null_for_required_fields_is_422(
        self, client: TestClient, ana: tuple[int, Headers], field: str
    ) -> None:
        task = create(client, ana[1])

        response = client.patch(
            f"/api/v1/tasks/{task['id']}", json={field: None}, headers=ana[1]
        )

        assert response.status_code == 422

    def test_completing_sets_and_reopening_clears_completed_at(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        url = f"/api/v1/tasks/{create(client, ana[1])['id']}"

        done = client.patch(url, json={"status": "completed"}, headers=ana[1]).json()
        assert done["completed_at"] is not None
        reopened = client.patch(url, json={"status": "pending"}, headers=ana[1]).json()
        assert reopened["completed_at"] is None

    def test_assignee_may_change_status_only(
        self, client: TestClient, ana: tuple[int, Headers], bo: tuple[int, Headers]
    ) -> None:
        url = f"/api/v1/tasks/{create(client, ana[1], assignee_id=bo[0])['id']}"

        ok = client.patch(url, json={"status": "in_progress"}, headers=bo[1])
        combined = client.patch(
            url, json={"status": "completed", "title": "x"}, headers=bo[1]
        )

        assert ok.status_code == 200
        assert combined.status_code == 403
        assert combined.json()["code"] == "forbidden_field"
        assert client.get(url, headers=ana[1]).json()["status"] == "in_progress"

    def test_outsider_gets_404(
        self, client: TestClient, ana: tuple[int, Headers], cy: tuple[int, Headers]
    ) -> None:
        url = f"/api/v1/tasks/{create(client, ana[1])['id']}"

        assert (
            client.patch(url, json={"status": "completed"}, headers=cy[1]).status_code
            == 404
        )

    def test_empty_patch_is_a_no_op(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        task = create(client, ana[1])

        response = client.patch(f"/api/v1/tasks/{task['id']}", json={}, headers=ana[1])

        assert response.status_code == 200
        assert response.json() == task


class TestDelete:
    def test_creator_deletes_with_204(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        url = f"/api/v1/tasks/{create(client, ana[1])['id']}"

        response = client.delete(url, headers=ana[1])

        assert response.status_code == 204
        assert response.content == b""
        assert client.get(url, headers=ana[1]).status_code == 404

    def test_assignee_gets_403_outsider_gets_404(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        bo: tuple[int, Headers],
        cy: tuple[int, Headers],
    ) -> None:
        url = f"/api/v1/tasks/{create(client, ana[1], assignee_id=bo[0])['id']}"

        assert client.delete(url, headers=bo[1]).status_code == 403
        assert client.delete(url, headers=cy[1]).status_code == 404
