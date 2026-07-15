import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models  # noqa: E402, F401  -- registers all 54 tables on Base.metadata
from app.database import Base, get_db_url  # noqa: E402
from app.db_init import alembic_include_name  # noqa: E402

config = context.config

# Only own logging when run standalone from the CLI. init_database() drives migrations
# in-process and passes its connection in; there, fileConfig() would reconfigure the
# root logger with disable_existing_loggers=True and silently kill every logger the app
# had already set up in configure_logging().
if config.config_file_name is not None and config.attributes.get("connection") is None:
    fileConfig(config.config_file_name)

# Resolved from DATA_DIR at runtime rather than hardcoded in alembic.ini, so the
# CLI and the app always migrate the same file.
config.set_main_option("sqlalchemy.url", get_db_url())

target_metadata = Base.metadata


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        include_name=alembic_include_name,
        # SQLite cannot ALTER/DROP a column in place; batch mode rebuilds the table.
        render_as_batch=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    # init_database() drives migrations over its own live connection; reuse it rather
    # than opening a second one against a WAL-locked file.
    connection = config.attributes.get("connection", None)
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
