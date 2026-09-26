"""Celery entry point used by the Compose `worker` service:

    celery -A app.infrastructure.worker_main worker

Settings are read at import time, so a misconfigured worker stops at startup.
The database engine is created on the first job, inside the pool process.
"""

from datetime import UTC, datetime
from functools import cache

from sqlalchemy.orm import sessionmaker

from app.application.exports import ExportRunner
from app.infrastructure.database import create_database_engine
from app.infrastructure.export_files import CsvExportFiles
from app.infrastructure.repositories import sql_unit_of_work
from app.infrastructure.settings import DatabaseSettings, ExportSettings, QueueSettings
from app.infrastructure.worker import create_worker_app

_database = DatabaseSettings()
_exports = ExportSettings()


@cache
def build_runner() -> ExportRunner:
    engine = create_database_engine(_database.url)
    return ExportRunner(
        uow=sql_unit_of_work(sessionmaker(bind=engine, expire_on_commit=False)),
        files=CsvExportFiles(_exports.dir),
        clock=lambda: datetime.now(UTC),
        ttl=_exports.ttl,
    )


app = create_worker_app(QueueSettings().resolved_broker_url(), build_runner)
