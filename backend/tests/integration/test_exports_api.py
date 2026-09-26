"""Export endpoints with a fake queue; the job is run in-process by the real
ExportRunner on the test transaction. test_exports_worker.py covers the real
Celery worker and Redis."""

import csv
import io
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.application.exports import ExportRunner
from app.infrastructure.export_files import HEADER, CsvExportFiles
from app.infrastructure.repositories import SqlUserRepository, sql_unit_of_work
from tests.fakes import FakeExportQueue
from tests.integration.conftest import savepoint_sessions, token_service

Headers = dict[str, str]
EXPORTS = "/api/v1/exports"


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
def run_export(connection: Connection, export_dir: Path) -> Callable[..., None]:
    def run(export_id: int, *, now: datetime | None = None) -> None:
        ExportRunner(
            uow=sql_unit_of_work(savepoint_sessions(connection)),
            files=CsvExportFiles(export_dir),
            clock=lambda: now or datetime.now(UTC),
            ttl=timedelta(hours=24),
        ).run(export_id)

    return run


def create_task(client: TestClient, headers: Headers, **body: Any) -> int:
    response = client.post(
        "/api/v1/tasks", json={"title": "Task", **body}, headers=headers
    )
    assert response.status_code == 201, response.text
    task_id: int = response.json()["id"]
    return task_id


def request_export(
    client: TestClient, headers: Headers, **filters: Any
) -> dict[str, Any]:
    response = client.post(EXPORTS, json=filters, headers=headers)
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


class TestRequest:
    def test_returns_202_with_a_pending_export_and_publishes_it(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        export_queue: FakeExportQueue,
    ) -> None:
        response = client.post(
            EXPORTS,
            json={"status": "in_progress", "due_date": "2026-10-01"},
            headers=ana[1],
        )

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        assert body["filters"] == {
            "status": "in_progress",
            "due_from": "2026-10-01",
            "due_to": "2026-10-01",
        }
        assert body["row_count"] is None and body["download_url"] is None
        assert response.headers["Location"] == f"{EXPORTS}/{body['id']}"
        assert export_queue.published == [body["id"]]

    def test_an_empty_body_exports_everything(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        body = request_export(client, ana[1])

        assert body["filters"] == {"status": None, "due_from": None, "due_to": None}

    @pytest.mark.parametrize(
        ("filters", "code"),
        [
            ({"due_from": "2026-10-02", "due_to": "2026-10-01"}, "invalid_due_range"),
            (
                {"due_date": "2026-10-01", "due_from": "2026-10-01"},
                "conflicting_due_filters",
            ),
            ({"status": "archived"}, None),
            ({"page": 2}, None),
        ],
    )
    def test_invalid_filters_are_rejected_and_nothing_is_published(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        export_queue: FakeExportQueue,
        filters: dict[str, Any],
        code: str | None,
    ) -> None:
        response = client.post(EXPORTS, json=filters, headers=ana[1])

        assert response.status_code == 422
        if code:
            assert response.json()["code"] == code
        assert export_queue.published == []

    def test_requires_authentication(self, client: TestClient) -> None:
        response = client.post(EXPORTS, json={})

        assert response.status_code == 401

    def test_unavailable_queue_returns_503(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        export_queue: FakeExportQueue,
    ) -> None:
        # That the failure is recorded is checked in test_exports_worker.py
        # with real commits: here the request's rollback also discards the
        # savepoints of the export's own transactions.
        export_queue.up = False

        response = client.post(EXPORTS, json={}, headers=ana[1])

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Exports are temporarily unavailable; try again later",
            "code": "queue_unavailable",
        }


class TestStatus:
    def test_requester_sees_progress_until_completion(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        run_export: Callable[..., None],
    ) -> None:
        create_task(client, ana[1])
        export = request_export(client, ana[1])

        pending = client.get(f"{EXPORTS}/{export['id']}", headers=ana[1]).json()
        run_export(export["id"])
        done = client.get(f"{EXPORTS}/{export['id']}", headers=ana[1]).json()

        assert pending["status"] == "pending"
        assert done["status"] == "completed"
        assert done["row_count"] == 1
        assert done["download_url"] == f"{EXPORTS}/{export['id']}/download"
        assert done["finished_at"] is not None and done["expires_at"] is not None

    def test_other_users_get_404(
        self, client: TestClient, ana: tuple[int, Headers], bo: tuple[int, Headers]
    ) -> None:
        export = request_export(client, ana[1])

        for url in (f"{EXPORTS}/{export['id']}", f"{EXPORTS}/{export['id']}/download"):
            response = client.get(url, headers=bo[1])
            assert response.status_code == 404
            assert response.json()["code"] == "export_not_found"

    def test_missing_export_gets_404(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        assert client.get(f"{EXPORTS}/999999", headers=ana[1]).status_code == 404


class TestDownload:
    def test_returns_the_requesters_visible_filtered_tasks_as_csv(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        bo: tuple[int, Headers],
        run_export: Callable[..., None],
    ) -> None:
        mine = create_task(client, ana[1], title="=cmd|' /C calc'!A0")
        assigned = create_task(client, bo[1], assignee_id=ana[0], due_date="2026-10-01")
        create_task(client, bo[1], title="Bo only")
        done = create_task(client, ana[1])
        client.patch(
            f"/api/v1/tasks/{done}", json={"status": "completed"}, headers=ana[1]
        )
        export = request_export(client, ana[1], status="pending")
        run_export(export["id"])

        response = client.get(f"{EXPORTS}/{export['id']}/download", headers=ana[1])

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        assert (
            f"tasks-export-{export['id']}.csv"
            in response.headers["content-disposition"]
        )
        assert response.headers["cache-control"] == "no-store"
        assert int(response.headers["content-length"]) == len(response.content)
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert rows[0] == list(HEADER)
        assert [int(r[0]) for r in rows[1:]] == [assigned, mine]
        assert rows[2][1] == "'=cmd|' /C calc'!A0"

    def test_pending_export_returns_409(
        self, client: TestClient, ana: tuple[int, Headers]
    ) -> None:
        export = request_export(client, ana[1])

        response = client.get(f"{EXPORTS}/{export['id']}/download", headers=ana[1])

        assert response.status_code == 409
        assert response.json()["code"] == "export_not_ready"

    def test_expired_export_returns_410(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        run_export: Callable[..., None],
    ) -> None:
        export = request_export(client, ana[1])
        run_export(export["id"], now=datetime.now(UTC) - timedelta(days=2))

        response = client.get(f"{EXPORTS}/{export['id']}/download", headers=ana[1])

        assert response.status_code == 410
        assert response.json()["code"] == "export_expired"

    def test_missing_file_returns_410(
        self,
        client: TestClient,
        ana: tuple[int, Headers],
        run_export: Callable[..., None],
        export_dir: Path,
    ) -> None:
        export = request_export(client, ana[1])
        run_export(export["id"])
        for file in export_dir.iterdir():
            file.unlink()

        response = client.get(f"{EXPORTS}/{export['id']}/download", headers=ana[1])

        assert response.status_code == 410
        assert response.json()["code"] == "export_file_missing"


def test_file_removed_after_validation_returns_410_not_500(
    client: TestClient,
    ana: tuple[int, Headers],
    run_export: Callable[..., None],
    export_dir: Path,
) -> None:
    # Maintenance can delete the file between the expiry check and opening
    # it: the response must still be a clean 410.
    export = request_export(client, ana[1])
    run_export(export["id"])
    files = client.app.state.export_files  # type: ignore[attr-defined]

    class VanishingFiles:
        def path(self, export_id: int) -> Path | None:
            found = files.path(export_id)
            if found is not None:
                found.unlink()
            return found

    client.app.state.export_files = VanishingFiles()  # type: ignore[attr-defined]

    response = client.get(f"{EXPORTS}/{export['id']}/download", headers=ana[1])

    assert response.status_code == 410
    assert response.json()["code"] == "export_file_missing"


def test_openapi_documents_the_export_flow(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]

    post = paths[EXPORTS]["post"]["responses"]
    assert {"202", "401", "422", "429", "503"} <= post.keys()
    download = paths[f"{EXPORTS}/{{export_id}}/download"]["get"]["responses"]
    assert {"200", "404", "409", "410"} <= download.keys()
    assert "text/csv" in download["200"]["content"]
