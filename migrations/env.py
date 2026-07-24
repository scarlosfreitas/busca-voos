"""Alembic migration environment for the busca-voos Medallion schema.

The connection URL comes from the environment (``persistence.db.build_database_url``),
never from ``alembic.ini`` (architecture.md §5). ``target_metadata`` is the Core
metadata in :mod:`persistence.tables`, so ``alembic revision --autogenerate`` can
diff future schema changes against it. ``include_schemas=True`` makes Alembic
aware of the bronze/silver/gold schemas.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from persistence.db import build_database_url
from persistence.tables import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve the URL from the environment (fail-fast if misconfigured).
config.set_main_option("sqlalchemy.url", build_database_url())

target_metadata = metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
