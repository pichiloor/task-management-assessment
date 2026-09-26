import csv
import stat
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.domain.task import Task, TaskStatus
from app.infrastructure.export_files import HEADER, CsvExportFiles, safe_cell

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def task(task_id: int, **overrides: object) -> Task:
    fields: dict[str, object] = {
        "title": f"Task {task_id}",
        "description": "",
        "creator_id": 1,
        "assignee_id": None,
        "due_date": None,
        "now": NOW,
    }
    fields.update(overrides)
    created = Task.create(**fields)  # type: ignore[arg-type]
    created.id = task_id
    return created


def read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


@pytest.fixture
def files(tmp_path: Path) -> CsvExportFiles:
    return CsvExportFiles(tmp_path / "exports")


def test_writes_a_header_and_one_row_per_task(files: CsvExportFiles) -> None:
    done = task(2, assignee_id=3, due_date=date(2026, 10, 1), description="Notes")
    done.change_status(TaskStatus.COMPLETED, now=NOW)

    count = files.write(7, [task(1), done])

    path = files.path(7)
    assert path is not None and count == 2
    header, first, second = read_rows(path)
    assert header == list(HEADER)
    assert first == [
        "1",
        "Task 1",
        "",
        "pending",
        "",
        "1",
        "",
        "",
        NOW.isoformat(),
        NOW.isoformat(),
    ]
    assert second == [
        "2",
        "Task 2",
        "Notes",
        "completed",
        "2026-10-01",
        "1",
        "3",
        NOW.isoformat(),
        NOW.isoformat(),
        NOW.isoformat(),
    ]


def test_starts_with_a_utf8_bom_so_spreadsheets_show_accents(
    files: CsvExportFiles,
) -> None:
    files.write(1, [task(1, title="Revisión de diseño")])

    path = files.path(1)
    assert path is not None
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_rows(path)[1][1] == "Revisión de diseño"


def test_an_empty_export_still_has_the_header(files: CsvExportFiles) -> None:
    assert files.write(1, []) == 0

    path = files.path(1)
    assert path is not None and read_rows(path) == [list(HEADER)]


@pytest.mark.parametrize(
    "value",
    ['=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"],
)
def test_cells_that_spreadsheets_would_run_as_formulas_are_neutralized(
    files: CsvExportFiles, value: str
) -> None:
    files.write(1, [task(1, title=value.strip() or "x", description=value)])

    path = files.path(1)
    assert path is not None
    row = read_rows(path)[1]
    assert row[2] == "'" + value
    assert safe_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["Plain", "a=b", "email@example.com", "", "3-2"])
def test_other_cells_are_unchanged(value: str) -> None:
    assert safe_cell(value) == value


def test_every_cell_is_quoted(files: CsvExportFiles) -> None:
    files.write(1, [task(1, description="line 1\nline 2, with comma")])

    path = files.path(1)
    assert path is not None
    text = path.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith('"id","title"')
    assert read_rows(path)[1][2] == "line 1\nline 2, with comma"


def test_rewriting_replaces_the_file(files: CsvExportFiles) -> None:
    files.write(1, [task(1), task(2)])
    files.write(1, [task(3)])

    path = files.path(1)
    assert path is not None
    assert [r[0] for r in read_rows(path)[1:]] == ["3"]


def test_a_failed_write_keeps_the_previous_file_and_leaves_no_temp_files(
    files: CsvExportFiles, tmp_path: Path
) -> None:
    files.write(1, [task(1)])

    def broken() -> Iterator[Task]:
        yield task(2)
        raise RuntimeError("database connection lost")

    with pytest.raises(RuntimeError):
        files.write(1, broken())

    path = files.path(1)
    assert path is not None
    assert [r[0] for r in read_rows(path)[1:]] == ["1"]
    assert sorted(p.name for p in (tmp_path / "exports").iterdir()) == [path.name]


def test_files_are_private_to_the_service_user(files: CsvExportFiles) -> None:
    files.write(1, [task(1)])

    path = files.path(1)
    assert path is not None
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_missing_file_has_no_path(files: CsvExportFiles) -> None:
    assert files.path(1) is None


def test_lists_and_deletes_export_files_only(
    files: CsvExportFiles, tmp_path: Path
) -> None:
    files.write(3, [task(1)])
    files.write(12, [task(2)])
    directory = tmp_path / "exports"
    (directory / "notes.txt").write_text("keep")
    (directory / "export-x.csv").write_text("not an export file name")
    (directory / ".export-5-abc.tmp").write_text("partial")

    assert files.export_ids() == [3, 12]

    files.delete(3)
    files.delete(3)  # already gone: no error

    assert files.export_ids() == [12]
    assert (directory / "notes.txt").exists()
    assert (directory / "export-x.csv").exists()


def test_removes_only_temp_files_older_than_the_cutoff(
    files: CsvExportFiles, tmp_path: Path
) -> None:
    import os
    from datetime import timedelta

    directory = tmp_path / "exports"
    files.write(1, [task(1)])
    old_temp = directory / ".export-3-abc.tmp"
    new_temp = directory / ".export-4-def.tmp"
    old_temp.write_text("partial")
    new_temp.write_text("partial")
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    long_ago = (cutoff - timedelta(hours=1)).timestamp()
    old_file = files.path(1)
    assert old_file is not None
    for path in (old_temp, old_file):
        os.utime(path, (long_ago, long_ago))

    assert files.remove_temp_older_than(cutoff) == 1

    assert not old_temp.exists() and new_temp.exists()
    assert files.path(1) is not None  # CSVs are removed by expiry, not age


def test_missing_directory_has_no_files(files: CsvExportFiles) -> None:
    assert files.export_ids() == []
    assert files.remove_temp_older_than(datetime.now(UTC)) == 0
