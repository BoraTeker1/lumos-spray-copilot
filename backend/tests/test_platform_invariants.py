"""Platform-level invariants that must survive every future phase.

Distinct from `test_invariants.py`, which guards the spray/compliance domain rules.
This file guards the *substrate*: schema semantics that mean different things on
different database backends, and structural boundaries the platform depends on.
"""
from sqlalchemy import inspect as sa_inspect

from app.database import Base, engine, partial_unique_index


# Every table whose uniqueness must apply only to LIVE rows, with the predicate that
# defines "live". A correction row deliberately repeats the natural key of the row it
# supersedes, so a FULL unique index here would make the append-only path impossible.
PARTIAL_UNIQUE_INDEXES = {
    "uq_weather_observation_station_hour": "supersedes_id IS NULL",
    "uq_pca_disposition_live_per_decision": "supersedes_id IS NULL",
    "uq_pilot_protocol_active_version": "effective_to IS NULL",
}


def _all_indexes():
    return {
        index.name: index
        for table in Base.metadata.tables.values()
        for index in table.indexes
    }


def test_partial_unique_indexes_declare_a_predicate_for_every_dialect():
    """A partial index must be partial on SQLite AND on PostgreSQL.

    `sqlite_where` alone is silently IGNORED by PostgreSQL: the index is still
    created, still unique, and no longer partial. The constraint would look present
    while meaning something strictly stronger than intended, and the first correction
    row written on Postgres would fail with an integrity error nobody predicted.
    """
    indexes = _all_indexes()
    for name, predicate in PARTIAL_UNIQUE_INDEXES.items():
        assert name in indexes, f"{name} is missing from the metadata entirely"
        index = indexes[name]
        assert index.unique, f"{name} must be unique"
        for dialect in ("sqlite", "postgresql"):
            clause = index.dialect_options[dialect].get("where")
            assert clause is not None, (
                f"{name} has no `where` predicate for {dialect}; on that backend it "
                f"would be a FULL unique index and would break the supersede chain"
            )
            assert str(clause) == predicate, (
                f"{name} predicate for {dialect} is {str(clause)!r}, expected {predicate!r}"
            )


def test_partial_unique_index_helper_emits_both_dialects():
    """The helper is the only sanctioned way to declare one; prove it stays correct."""
    index = partial_unique_index("uq_probe", "a", "b", where="c IS NULL")
    assert index.unique
    assert str(index.dialect_options["sqlite"]["where"]) == "c IS NULL"
    assert str(index.dialect_options["postgresql"]["where"]) == "c IS NULL"


def test_partial_predicates_actually_reach_the_live_database(client):
    """Guard against the predicate being declared but dropped at DDL time.

    Reads the index back out of the running database rather than the metadata, so a
    dialect that accepted the kwarg and discarded it is caught. Takes `client` only
    to get a freshly created schema.
    """
    inspector = sa_inspect(engine)
    dialect = engine.dialect.name
    if dialect not in ("sqlite", "postgresql"):
        return  # nothing to assert about a backend we do not support
    found = {}
    for table_name in inspector.get_table_names():
        for index in inspector.get_indexes(table_name):
            if index["name"] in PARTIAL_UNIQUE_INDEXES:
                found[index["name"]] = index
    for name in PARTIAL_UNIQUE_INDEXES:
        assert name in found, f"{name} was never created in the database"
        assert found[name]["unique"], f"{name} lost its uniqueness at DDL time"
