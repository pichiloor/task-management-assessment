"""The integration suite drops and recreates its database, so the guard that
picks that database must never be fooled into targeting a real one."""

import pytest
from sqlalchemy.engine import URL

from tests.support.database import (
    UnsafeTestDatabaseError,
    alembic_config,
    integration_database_url,
)

ENV = {
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "secret",  # pragma: allowlist secret
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": "5432",
    "TEST_POSTGRES_DB": "task_management_test",
}


def env(**overrides: str) -> dict[str, str]:
    return {**ENV, **overrides}


def test_builds_url_from_components() -> None:
    url = integration_database_url(env())

    assert url.database == "task_management_test"
    assert url.host == "db"


def test_reserved_characters_in_password_survive() -> None:
    password = "p@ss:w/rd%"  # pragma: allowlist secret
    url = integration_database_url(env(POSTGRES_PASSWORD=password))

    assert url.password == password
    assert url.host == "db"


@pytest.mark.parametrize(
    "name",
    [
        "task_management",  # the development database itself
        "task_management_testing",
        'x_test"; DROP DATABASE task_management; --',
        "Upper_test",
    ],
)
def test_rejects_names_that_are_not_plain_test_databases(name: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError):
        integration_database_url(env(TEST_POSTGRES_DB=name))


def test_rejects_names_postgres_would_truncate() -> None:
    # PostgreSQL silently truncates identifiers to 63 bytes, so a longer
    # "<real db>_test" name could resolve to the real database.
    name = "a" * 59 + "_test"
    assert len(name) == 64

    with pytest.raises(UnsafeTestDatabaseError):
        integration_database_url(env(TEST_POSTGRES_DB=name))


def test_accepts_the_longest_safe_name() -> None:
    name = "a" * 58 + "_test"

    assert integration_database_url(env(TEST_POSTGRES_DB=name)).database == name


def test_alembic_config_accepts_urls_with_percent_signs() -> None:
    url = URL.create(
        "postgresql+psycopg",
        username="app",
        password="100%secret",  # pragma: allowlist secret
        host="db",
        database="x_test",
    )

    config = alembic_config(url)

    assert config.attributes["url"] == url
