"""The Alembic chain must produce the same schema the app builds with create_all.

Nothing verified this before: the runtime path is `Base.metadata.create_all` (tests,
fresh demo DBs) while real pilot databases evolve through `alembic upgrade head`. A
model change that never got a migration is invisible until it hits real data — which is
exactly when it is least recoverable.

The round-trip test also proves `downgrade` runs, so the migration is reversible rather
than reversible-in-theory.
"""
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.database import Base, engine

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

# Alembic's own bookkeeping table has no model and is expected to differ.
_ALEMBIC_TABLE = "alembic_version"


@pytest.fixture()
def migrated_db():
    """A schema built purely by `alembic upgrade head`, torn down afterwards."""
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {_ALEMBIC_TABLE}"))
    cfg = Config(str(ALEMBIC_INI))
    command.upgrade(cfg, "head")
    yield cfg
    # Leave the DB clean for the next test's `client` fixture.
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {_ALEMBIC_TABLE}"))


def _schema_from_db() -> dict[str, set[str]]:
    inspector = inspect(engine)
    return {
        table: {col["name"] for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != _ALEMBIC_TABLE
    }


def _schema_from_models() -> dict[str, set[str]]:
    return {t.name: set(t.columns.keys()) for t in Base.metadata.sorted_tables}


def test_alembic_head_matches_the_models(migrated_db):
    migrated = _schema_from_db()
    expected = _schema_from_models()

    missing_tables = sorted(set(expected) - set(migrated))
    extra_tables = sorted(set(migrated) - set(expected))
    assert not missing_tables, (
        f"tables exist in models.py but no migration creates them: {missing_tables} — "
        f"run `alembic revision --autogenerate` and review the script"
    )
    assert not extra_tables, f"migrations create tables no model declares: {extra_tables}"

    for table in sorted(expected):
        missing_cols = sorted(expected[table] - migrated[table])
        extra_cols = sorted(migrated[table] - expected[table])
        assert not missing_cols, f"{table}: columns missing from the migration chain: {missing_cols}"
        assert not extra_cols, f"{table}: columns in the migration chain but not the model: {extra_cols}"


def test_migration_chain_round_trips(migrated_db):
    """Every revision downgrades cleanly back to base and upgrades again."""
    command.downgrade(migrated_db, "base")
    remaining = [t for t in inspect(engine).get_table_names() if t != _ALEMBIC_TABLE]
    assert remaining == [], f"downgrade left tables behind: {remaining}"

    command.upgrade(migrated_db, "head")
    assert _schema_from_db() == _schema_from_models()
