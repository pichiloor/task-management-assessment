import importlib
import sys
from types import ModuleType

import pytest
from pydantic import ValidationError

from app.infrastructure.worker import RUN_EXPORT

ENV = {
    "POSTGRES_USER": "app",
    "POSTGRES_PASSWORD": "pw",  # pragma: allowlist secret
    "POSTGRES_DB": "app",
    "REDIS_URL": "redis://localhost:6379/0",
}


def load(monkeypatch: pytest.MonkeyPatch, **env: str) -> ModuleType:
    for key, value in (ENV | env).items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("app.infrastructure.worker_main", None)
    return importlib.import_module("app.infrastructure.worker_main")


def test_worker_uses_the_dedicated_broker_and_registers_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load(monkeypatch, CELERY_BROKER_URL="redis://redis:6379/1")

    assert module.app.conf.broker_url == "redis://redis:6379/1"
    assert RUN_EXPORT in module.app.tasks


def test_broker_defaults_to_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)

    module = load(monkeypatch)

    assert module.app.conf.broker_url == "redis://localhost:6379/0"


def test_missing_database_settings_stop_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    sys.modules.pop("app.infrastructure.worker_main", None)
    for key in ("POSTGRES_USER", "POSTGRES_DB"):
        monkeypatch.setenv(key, "app")

    with pytest.raises(ValidationError):
        importlib.import_module("app.infrastructure.worker_main")


def test_runner_is_built_once_without_connecting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    module = load(monkeypatch, EXPORT_DIR=str(tmp_path))
    module.build_runner.cache_clear()

    assert module.build_runner() is module.build_runner()
