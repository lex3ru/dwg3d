"""The service's own database, and the two tables every service has.

  outbox  events waiting to be published: written in the same transaction as
          the change they describe, sent to NATS after it (bus.py)
  inbox   events already handled, per handler — a redelivery does nothing

Services declare their tables on `metadata`, so one Alembic history covers both.

The pool of connections is small and bounded — TWIN_DB_POOL kept open (default 5), as many again
when busy; past that a request waits for a free one rather than failing. All the services and
Keycloak share one Postgres: see the budget of connections in deploy/README.md.
"""
from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from sqlalchemy import Column, DateTime, MetaData, Table, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s", "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"})

outbox = Table(
    "outbox", metadata,
    Column("id", Uuid, primary_key=True),                    # the event's id
    Column("type", Text, nullable=False),
    Column("payload", JSONB, nullable=False),                # the whole envelope
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("published_at", DateTime(timezone=True)),
)
inbox = Table(
    "inbox", metadata,
    Column("event_id", Uuid, primary_key=True),
    Column("handler", Text, primary_key=True),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


def uuid7() -> uuid.UUID:
    """A time-ordered UUID (version 7): 48 bits of milliseconds, the rest random."""
    ms = time.time_ns() // 1_000_000
    b = bytearray(ms.to_bytes(6, "big") + os.urandom(10))
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return uuid.UUID(bytes=bytes(b))


class Database:
    def __init__(self, url: str, *, pooled: bool = True):
        self.url = url
        size = int(os.environ.get("TWIN_DB_POOL", "5"))
        self.engine = (create_async_engine(url, pool_pre_ping=True, pool_size=size, max_overflow=size, pool_timeout=30)
                       if pooled else create_async_engine(url, poolclass=NullPool))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.after_commit: Callable[[], None] = lambda: None     # the bus hooks in: "there may be new events"

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncSession]:
        """One transaction: commits on leaving, rolls back on an exception."""
        async with self.sessions() as session:
            async with session.begin():
                yield session
        self.after_commit()

    async def ok(self) -> bool:
        try:
            async with self.engine.connect() as c:
                await c.execute(text("select 1"))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self.engine.dispose()
