"""Shared pytest fixtures.

Binds the app to a throwaway SQLite database *before* importing anything from `app`
(the engine is created at import time), and resets tables between tests for isolation.
The dev DB is never touched.
"""
import os
import tempfile

# Must run before any `app` import binds the engine.
_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["LUMOS_DATABASE_URL"] = f"sqlite:///{_TMP.name}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """A TestClient backed by a fresh, empty schema for each test."""
    Base.metadata.drop_all(bind=engine)
    init_db()
    with TestClient(app) as c:
        yield c
