"""CSV export files on a directory shared by the API and the worker (a Docker
volume outside any public path). File names come from the export ID only."""

import csv
import os
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from app.domain.task import Task

HEADER = (
    "id",
    "title",
    "description",
    "status",
    "due_date",
    "creator_id",
    "assignee_id",
    "completed_at",
    "created_at",
    "updated_at",
)

# A cell starting with one of these is run as a formula by spreadsheet apps
# (CSV injection, OWASP): it is prefixed with a quote so it stays text.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: str) -> str:
    return "'" + value if value.startswith(FORMULA_PREFIXES) else value


def _row(task: Task) -> list[str]:
    def text(value: object) -> str:
        if value is None:
            return ""
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    return [
        text(task.id),
        safe_cell(task.title),
        safe_cell(task.description),
        task.status.value,
        text(task.due_date),
        text(task.creator_id),
        text(task.assignee_id),
        text(task.completed_at),
        text(task.created_at),
        text(task.updated_at),
    ]


class CsvExportFiles:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _file(self, export_id: int) -> Path:
        return self._directory / f"export-{int(export_id)}.csv"

    def write(self, export_id: int, tasks: Iterable[Task]) -> int:
        """Writes to a temporary file and renames it into place, so readers
        never see a partial file and a failed write keeps the previous one."""
        self._directory.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            dir=self._directory, prefix=f".export-{int(export_id)}-", suffix=".tmp"
        )
        try:
            # UTF-8 with BOM: spreadsheet apps otherwise misread accents.
            with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                writer.writerow(HEADER)
                count = 0
                for task in tasks:
                    writer.writerow(_row(task))
                    count += 1
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self._file(export_id))
        except BaseException:
            with suppress(FileNotFoundError):
                os.unlink(temp)
            raise
        return count

    def path(self, export_id: int) -> Path | None:
        file = self._file(export_id)
        return file if file.is_file() else None

    def remove_older_than(
        self, *, files_before: datetime, temp_before: datetime
    ) -> int:
        """Only files this class names are touched. A download already in
        progress keeps reading an unlinked file (POSIX semantics)."""
        removed = 0
        for pattern, cutoff in (
            ("export-*.csv", files_before),
            (".export-*.tmp", temp_before),
        ):
            for file in self._directory.glob(pattern):
                with suppress(FileNotFoundError):
                    if file.stat().st_mtime < cutoff.timestamp():
                        file.unlink()
                        removed += 1
        return removed
