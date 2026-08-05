"""The Alembic chain must produce the same schema the app builds with create_all.

Nothing verified this before: the runtime path is `Base.metadata.create_all` (tests,
fresh demo DBs) while real pilot databases evolve through `alembic upgrade head`. A
model change that never got a migration is invisible until it hits real data — which is
exactly when it is least recoverable.

The round-trip test also proves `downgrade` runs, so the migration is reversible rather
than reversible-in-theory.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app import crud
from app.database import Base, engine

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

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


# --------------------------------------------------------------------------- #
# The spine backfill's demo/real derivation.                                   #
#                                                                              #
# `farms` has no provenance column, so the backfill asks the farm's RECORDS    #
# whether it is a demo farm — the same question `ensure_demo_real_separation`  #
# asks. Two things can go wrong silently: the migration's table list can drift #
# away from `crud._FARM_RECORD_MODELS`, and the derivation itself can get a    #
# case wrong. A wrong answer mints a spine row that either lets simulated data #
# be counted as real, or blocks a real farm's first write.                     #
# --------------------------------------------------------------------------- #

def _backfill_module():
    """Import the backfill migration by path (it is not on the import path)."""
    path = VERSIONS / "d4c9129576bd_p0_backfill_spine_from_farms.py"
    spec = importlib.util.spec_from_file_location("_backfill_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_backfill_scans_exactly_the_farm_record_models():
    """Adding a model to `_FARM_RECORD_MODELS` must not silently bypass the backfill.

    A migration cannot import `app.models` (it must describe the schema as it was at
    its own revision), so the table list is duplicated by necessity. This is the guard
    that makes the duplication safe.
    """
    module = _backfill_module()
    assert set(module.FARM_RECORD_TABLES) == {
        model.__tablename__ for model in crud._FARM_RECORD_MODELS
    }, (
        "the backfill's FARM_RECORD_TABLES has drifted from crud._FARM_RECORD_MODELS — "
        "update alembic/versions/d4c9129576bd_p0_backfill_spine_from_farms.py"
    )


@pytest.fixture()
def provenance_db(tmp_path):
    """A throwaway DB holding only the columns `farm_provenance` reads."""
    module = _backfill_module()
    db_engine = create_engine(f"sqlite:///{tmp_path / 'provenance.db'}")
    with db_engine.begin() as conn:
        for table in module.FARM_RECORD_TABLES:
            conn.execute(text(
                f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, farm_id INTEGER, "
                f"data_source TEXT, data_confidence TEXT)"
            ))
    yield SimpleNamespace(engine=db_engine, module=module)
    db_engine.dispose()


def _insert(conn, farm_id, data_source, data_confidence):
    conn.execute(
        text("INSERT INTO spray_events (farm_id, data_source, data_confidence) "
             "VALUES (:farm, :src, :conf)"),
        {"farm": farm_id, "src": data_source, "conf": data_confidence},
    )


def test_demo_nature_is_derived_from_records_not_from_a_farm_column(provenance_db):
    """The four cases, including the one that must refuse to answer."""
    module = provenance_db.module
    with provenance_db.engine.begin() as conn:
        _insert(conn, 1, "demo", "simulated")
        _insert(conn, 2, "manual_entry", "user_provided")
        _insert(conn, 3, "demo", "simulated")
        _insert(conn, 3, "manual_entry", "user_provided")

        # A farm whose records are all demo produces demo scaffolding.
        assert module.farm_provenance(conn, 1) == ("demo", "simulated")

        # A farm whose records are all real produces real, derived scaffolding.
        assert module.farm_provenance(conn, 2) == ("manual_entry", module.DERIVED)

        # A farm with no records at all cannot be proven demo, so it is treated as
        # real — matching crud.has_non_demo_data's existing stance.
        assert module.farm_provenance(conn, 999) == ("manual_entry", module.DERIVED)

        # A farm holding both already violates the mixing guard. Refuse, loudly.
        with pytest.raises(module.MixedProvenanceFarm) as excinfo:
            module.farm_provenance(conn, 3)
        assert "farm 3" in str(excinfo.value)


def test_either_provenance_marker_alone_makes_a_record_demo(provenance_db):
    """Mirrors decision_status.is_demo_record: the predicate is OR, not AND.

    A row tagged `data_confidence="simulated"` with an unremarkable `data_source` is
    still simulated, and vice versa. Reading only one column would let seeded data
    through as real.
    """
    module = provenance_db.module
    with provenance_db.engine.begin() as conn:
        _insert(conn, 10, "manual_entry", "simulated")
        _insert(conn, 11, "demo", "user_provided")
        assert module.farm_provenance(conn, 10) == ("demo", "simulated")
        assert module.farm_provenance(conn, 11) == ("demo", "simulated")
