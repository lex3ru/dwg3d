"""The service's Alembic migrations.

    python -m twin_chassis.migrate            # upgrade to head; run before the service starts

The service has `migrations/versions/*.py` next to its package, and nothing
else: this module is the Alembic environment. Replicas starting together
queue on an advisory lock. The first migration of a service calls
`create_chassis_tables()`.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import JSONB

from .db import metadata

LOCK_KEY = 0x7477696E      # "twin"


def create_chassis_tables() -> None:
    """outbox and inbox (db.py), for the first migration of a service."""
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_pending", "outbox", ["created_at"], postgresql_where=sa.text("published_at IS NULL"))
    op.create_table(
        "inbox",
        sa.Column("event_id", sa.Uuid, primary_key=True),
        sa.Column("handler", sa.Text, primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade(database_url: str, migrations: Path | str = "migrations", revision: str = "head") -> None:
    migrations = Path(migrations).resolve()
    config = Config()
    config.set_main_option("script_location", str(migrations))
    script = ScriptDirectory(str(migrations), version_locations=[str(migrations / "versions")])
    engine = sa.create_engine(database_url, poolclass=sa.pool.NullPool)

    def run(rev, context):
        return script._upgrade_revs(revision, rev)

    with engine.connect() as connection:
        connection.execute(sa.text("select pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        connection.commit()
        try:
            with EnvironmentContext(config, script, fn=run, destination_rev=revision) as env:
                env.configure(connection=connection, target_metadata=metadata)
                with env.begin_transaction():
                    env.run_migrations()
            connection.commit()
        finally:
            connection.execute(sa.text("select pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            connection.commit()
    engine.dispose()


if __name__ == "__main__":
    url = os.environ.get("TWIN_DATABASE_URL")
    if not url:
        sys.exit("Задайте TWIN_DATABASE_URL")
    upgrade(url)
    print("migrations: up to date")
