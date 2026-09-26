"""PostgreSQL fixtures. Integration tests run only when TEST_POSTGRES_DB is set
(Compose `backend-tests` service and CI); otherwise they are skipped.

The test database is dropped and rebuilt with Alembic once per session, and
every test runs inside a transaction that is rolled back afterwards.
"""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from tests.support.database import alembic_config, integration_database_url

if not os.environ.get("TEST_POSTGRES_DB"):
    pytest.skip("TEST_POSTGRES_DB is not set", allow_module_level=True)


def _recreate_database(url: URL) -> None:
    # The name was validated by integration_database_url, so quoting it is safe.
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> URL:
    url = integration_database_url(os.environ)
    _recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(database_url: URL) -> Iterator[Engine]:
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def connection(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as conn:
        transaction = conn.begin()
        yield conn
        transaction.rollback()


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    # Commits inside the code under test become savepoints of the outer
    # transaction, so the rollback above still discards everything.
    with Session(bind=connection, join_transaction_mode="create_savepoint") as s:
        yield s
