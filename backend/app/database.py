"""Database setup: SQLite engine, session factory, and declarative base.

Kept intentionally small. Routes get a session via the `get_db` dependency so that
an auth/tenant dependency can be layered in later without touching business logic.
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Store the SQLite file next to the backend package by default.
DB_PATH = os.environ.get(
    "LUMOS_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "lumos.db"),
)
DATABASE_URL = os.environ.get("LUMOS_DATABASE_URL", f"sqlite:///{DB_PATH}")

# check_same_thread=False is required for SQLite when used with FastAPI's threadpool.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


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
