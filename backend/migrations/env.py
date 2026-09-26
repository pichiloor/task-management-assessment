from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, create_engine

from app.infrastructure.models import Base
from app.infrastructure.settings import database_settings

config = context.config
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _url() -> URL:
    # A URL passed programmatically (tests) wins over the POSTGRES_* variables.
    override = config.attributes.get("url")
    if isinstance(override, URL):
        return override
    return database_settings().url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
