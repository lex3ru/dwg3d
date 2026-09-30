"""Tests that touch the database run on a real PostgreSQL (JSONB and row
locks behave differently in SQLite): a scratch database is created next to
the one in DWG3D_TEST_DATABASE_URL (default: the docker compose service),
migrated, and dropped at the end. Without a server those tests are skipped.

  docker compose up -d db && uv run pytest
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from dwg3d import catalog, db

BASE_URL = make_url(os.environ.get("DWG3D_TEST_DATABASE_URL") or db.DEFAULT_URL)
TEST_URL = BASE_URL.set(database=f"dwg3d_test_{uuid.uuid4().hex[:8]}")
# every module that imports dwg3d.api must see the scratch database, never the real one
os.environ["DWG3D_DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)
# API tests run without sign-in; test_auth.py turns it on
os.environ["DWG3D_AUTH"] = "off"


def _admin():
    return create_engine(BASE_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session")
def pg():
    """URL of a freshly migrated scratch database (catalog loaded)."""
    admin = _admin()
    try:
        with admin.connect() as c:
            c.execute(text(f'CREATE DATABASE "{TEST_URL.database}"'))
    except Exception as ex:
        admin.dispose()
        pytest.skip(f"PostgreSQL недоступен ({BASE_URL.host}:{BASE_URL.port}): {ex.__class__.__name__}")
    db.reset()
    db.migrate()
    catalog.load()
    yield TEST_URL
    db.reset()
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_URL.database}" WITH (FORCE)'))
    admin.dispose()
