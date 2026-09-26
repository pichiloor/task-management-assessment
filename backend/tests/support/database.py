"""Selects and configures the throwaway database of the integration suite.

The suite runs DROP DATABASE on this target, so the name is validated before
any SQL is sent. It must be exactly the application database name plus
`_test` (so it can never be the application database itself), a plain
lowercase identifier, and fit in PostgreSQL's 63-byte limit: a longer name
would be silently truncated by the server and could resolve to a real one.
"""

import re
from collections.abc import Mapping
from pathlib import Path

from alembic.config import Config
from sqlalchemy.engine import URL

BACKEND_DIR = Path(__file__).resolve().parents[2]
POSTGRES_IDENTIFIER_MAX_BYTES = 63
_SAFE_NAME = re.compile(r"[a-z_][a-z0-9_]*_test")


class UnsafeTestDatabaseError(RuntimeError):
    pass


def integration_database_url(env: Mapping[str, str]) -> URL:
    name = env["TEST_POSTGRES_DB"]
    expected = env["POSTGRES_DB"] + "_test"
    if name != expected:
        raise UnsafeTestDatabaseError(
            f"TEST_POSTGRES_DB must be {expected!r} (POSTGRES_DB + '_test'), "
            f"got {name!r}"
        )
    if not _SAFE_NAME.fullmatch(name):
        raise UnsafeTestDatabaseError(
            f"{name!r} is not a lowercase identifier ending in _test"
        )
    if len(name.encode()) > POSTGRES_IDENTIFIER_MAX_BYTES:
        raise UnsafeTestDatabaseError(
            f"{name!r} exceeds {POSTGRES_IDENTIFIER_MAX_BYTES} bytes and would be "
            "truncated by PostgreSQL"
        )
    # Components, not a pre-built string, so reserved characters in the
    # password need no URL encoding.
    return URL.create(
        "postgresql+psycopg",
        username=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        host=env.get("POSTGRES_HOST", "db"),
        port=int(env.get("POSTGRES_PORT", "5432")),
        database=name,
    )


def alembic_config(url: URL) -> Config:
    # Passed as an attribute: set_main_option would run ConfigParser
    # interpolation over a '%' in the password.
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.attributes["url"] = url
    return config
