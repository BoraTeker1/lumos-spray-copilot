"""Database setup: engine, session factory, declarative base, dialect helpers.

Kept intentionally small. Routes get a session via the `get_db` dependency so that
an auth/tenant dependency can be layered in later without touching business logic.

The engine is dialect-agnostic: `LUMOS_DATABASE_URL` selects SQLite (the historical
default) or PostgreSQL. Everything dialect-specific lives in this module so no model,
route, or migration has to branch on the backend.
"""
import os

from sqlalchemy import Index, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Store the SQLite file next to the backend package by default.
DB_PATH = os.environ.get(
    "LUMOS_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "lumos.db"),
)
DATABASE_URL = os.environ.get("LUMOS_DATABASE_URL", f"sqlite:///{DB_PATH}")

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgres")


def _engine_kwargs() -> dict:
    if IS_SQLITE:
        # check_same_thread=False is required for SQLite under FastAPI's threadpool.
        return {"connect_args": {"check_same_thread": False}}
    # Modest pool: one app process + one worker process, both talking to one database.
    # pool_pre_ping avoids handing out connections a restart or timeout has killed.
    return {
        "pool_size": int(os.environ.get("LUMOS_DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("LUMOS_DB_MAX_OVERFLOW", "10")),
        "pool_pre_ping": True,
    }


engine = create_engine(DATABASE_URL, **_engine_kwargs())

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def partial_unique_index(name: str, *columns: str, where: str) -> Index:
    """A unique index that applies only to rows matching `where`.

    Load-bearing for every append-only table in this system. A correction row
    deliberately repeats the natural key of the row it supersedes, so the uniqueness
    must be scoped to live rows (`supersedes_id IS NULL`, `effective_to IS NULL`).

    This helper exists because the predicate has to be declared once per dialect:
    `sqlite_where` alone is silently IGNORED by PostgreSQL, which would create a FULL
    unique index and make the append-only correction path impossible — the constraint
    would look present and mean something stricter than intended. Emitting both keeps
    the two backends honest with each other.
    """
    predicate = text(where)
    return Index(
        name,
        *columns,
        unique=True,
        sqlite_where=predicate,
        postgresql_where=predicate,
    )


def get_db():
    """FastAPI dependency that yields a database session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Safe to call repeatedly."""
    # Import models so they are registered on the metadata before create_all.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
