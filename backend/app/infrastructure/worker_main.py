"""Celery entry point used by the Compose `worker` service:

    celery -A app.infrastructure.worker_main worker
    celery -A app.infrastructure.worker_main beat   # periodic maintenance

Settings are read at import time, so a misconfigured worker stops at startup.
The database engine is created on the first job, inside the pool process.
"""

from datetime import UTC, datetime
from functools import cache

from sqlalchemy.orm import sessionmaker

from app.application.exports import ExportMaintenance, ExportRunner
from app.application.ports import UnitOfWorkFactory
from app.infrastructure.database import create_database_engine
from app.infrastructure.export_files import CsvExportFiles
from app.infrastructure.repositories import sql_unit_of_work
from app.infrastructure.settings import DatabaseSettings, ExportSettings, QueueSettings
from app.infrastructure.worker import CeleryExportQueue, create_worker_app

_database = DatabaseSettings()
_exports = ExportSettings()


def _now() -> datetime:
    return datetime.now(UTC)


@cache
def _unit_of_work() -> UnitOfWorkFactory:
    engine = create_database_engine(_database.url)
    return sql_unit_of_work(sessionmaker(bind=engine, expire_on_commit=False))


@cache
def build_runner() -> ExportRunner:
    return ExportRunner(
        uow=_unit_of_work(),
        files=CsvExportFiles(_exports.dir),
        clock=_now,
        ttl=_exports.ttl,
    )


@cache
def build_maintenance() -> ExportMaintenance:
    return ExportMaintenance(
        uow=_unit_of_work(),
        queue=CeleryExportQueue(app),
        files=CsvExportFiles(_exports.dir),
        clock=_now,
        ttl=_exports.ttl,
    )


app = create_worker_app(
    QueueSettings().resolved_broker_url(), build_runner, build_maintenance
)
