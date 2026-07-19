"""Alembic environment — wired to the app's own engine URL and metadata.

The database URL is the SAME resolution the app uses (app.database: LUMOS_DATABASE_URL
/ LUMOS_DB_PATH env vars, defaulting to backend/lumos.db), so migrations always target
the database the app would open — the sqlalchemy.url in alembic.ini is ignored.

Workflow (SQLite, no branching expected):
* Fresh demo DB: `python -m app.seed` creates the full schema (create_all), then
  `alembic stamp head` marks it current.
* Schema change: edit app/models.py, `alembic revision --autogenerate -m "..."`,
  review the generated script (SQLite needs batch mode for ALTER — enabled below),
  then `alembic upgrade head`.
"""
from logging.config import fileConfig

from alembic import context

from app.database import DATABASE_URL, Base, engine
from app import models  # noqa: F401  (register every model on the metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live connection."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite can't ALTER in place — batch mode rewrites tables
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the app's engine."""
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite can't ALTER in place — batch mode rewrites tables
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
