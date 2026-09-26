"""PostgreSQL fixtures. Integration tests run only when TEST_DATABASE_URL is set
(Compose `backend-tests` service and CI); otherwise they are skipped.

The test database is dropped and rebuilt with Alembic once per session, and
every test runs inside a transaction that is rolled back afterwards.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set", allow_module_level=True)
    return url


def _recreate_database(url: str) -> None:
    target = make_url(url)
    assert target.database and target.database.endswith("_test"), (
        "refusing to drop a database whose name does not end in _test"
    )
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url()
    _recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
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
