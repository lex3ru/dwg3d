"""PostgreSQL access: engine, sessions, ORM base, schema migrations.

  DWG3D_DATABASE_URL   SQLAlchemy URL (default: the docker compose service,
                       postgresql+psycopg://dwg3d:dwg3d@127.0.0.1:5432/dwg3d)

The schema is owned by Alembic (dwg3d/migrations); `migrate()` brings the
database to the latest revision and is run by the API on start-up and by
`python -m dwg3d db upgrade`.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://dwg3d:dwg3d@127.0.0.1:5432/dwg3d"
MIGRATIONS = Path(__file__).with_name("migrations")
# serialises concurrent `migrate()` calls (several API processes starting at once)
_MIGRATE_LOCK = 0x64776733


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def database_url() -> str:
    return os.environ.get("DWG3D_DATABASE_URL") or DEFAULT_URL


def engine() -> Engine:
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset():
    """Drop the pool (tests switch databases; forked workers must not share sockets)."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _Session = None


@contextmanager
def session():
    """Transaction scope: commits on success, rolls back on error."""
    engine()
    with _Session() as s, s.begin():
        yield s


def alembic_config(url: str | None = None):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.set_main_option("sqlalchemy.url", (url or database_url()).replace("%", "%%"))
    return cfg


def migrate(revision: str = "head"):
    from alembic import command

    with engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATE_LOCK})
        try:
            cfg = alembic_config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, revision)
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATE_LOCK})
            conn.commit()


def ping() -> bool:
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
