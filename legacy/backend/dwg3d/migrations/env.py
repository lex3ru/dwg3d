"""Alembic environment. `dwg3d.db.migrate()` passes an open connection in
`config.attributes["connection"]`; the alembic CLI (backend/alembic.ini)
connects by URL."""
from alembic import context
from sqlalchemy import create_engine

from dwg3d import models  # noqa: F401  (registers the tables on Base.metadata)
from dwg3d.db import Base, database_url

config = context.config
target_metadata = Base.metadata


def run_offline():
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online():
    conn = config.attributes.get("connection")
    if conn is not None:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    with create_engine(database_url()).connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
