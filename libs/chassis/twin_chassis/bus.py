"""The event bus: NATS JetStream, one stream for all services.

Publishing: rows of the outbox go to `twin.<type>`; a row is marked published
only after NATS has stored it. While NATS is away the service keeps working
and the rows wait.

Consuming: `@bus.consumer("buildings.room.retired")` registers a handler; it
runs in a transaction together with the inbox row of that event, so a
redelivered event is handled once. A handler that raises is retried.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import nats
from nats.js.api import StreamConfig
from nats.js.errors import BadRequestError, NotFoundError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .db import Database, inbox, outbox

log = logging.getLogger("twin.bus")
Handler = Callable[[AsyncSession, dict], Awaitable[None]]
KEEP_EVENTS = timedelta(days=30)        # in the stream
KEEP_OUTBOX = timedelta(days=7)         # published rows
KEEP_INBOX = timedelta(days=35)


class Bus:
    def __init__(self, service: str, url: str, db: Database, prefix: str = "twin"):
        self.service, self.url, self.db = service, url, db
        self.stream, self.subject = prefix.upper(), prefix + "."       # stream TWIN, subjects twin.<event type>
        self.live = prefix + "-live."                                  # not stored: twin-live.<event type>
        self.nc: nats.NATS | None = None
        self.js = None
        self._handlers: dict[str, tuple[str, Handler]] = {}       # name -> (event type pattern, handler)
        self._listeners: list[tuple[str, Callable[[dict], None]]] = []
        self._tasks: list[asyncio.Task] = []
        self._wake = asyncio.Event()
        self._ready = asyncio.Event()                             # connected and the stream exists
        db.after_commit = self._wake.set

    # ---------------------------------------------------------- handlers ---
    def consumer(self, pattern: str, name: str | None = None):
        """Register a handler of events whose type matches `pattern` (NATS wildcards allowed)."""
        def register(fn: Handler) -> Handler:
            self._handlers[name or fn.__name__] = (pattern, fn)
            return fn
        return register

    def listen(self, pattern: str, callback: Callable[[dict], None]) -> None:
        """Hear matching events as they pass, with no memory and no guarantees:
        what happened while disconnected is missed. For showing, not for acting."""
        self._listeners.append((pattern, callback))

    async def announce(self, event: dict) -> None:
        """Tell whoever is listening now and forget: progress of a long job and
        the like. Not stored, not retried, never to be acted upon."""
        if self.connected:
            try:
                await self.nc.publish(self.live + event["type"], json.dumps(event, ensure_ascii=False).encode())
            except Exception:
                pass

    async def handle(self, name: str, event: dict) -> bool:
        """Run the handler for the event unless it already did; False for a repeat."""
        _, fn = self._handlers[name]
        async with self.db.begin() as session:
            first = await session.execute(pg_insert(inbox).values(event_id=UUID(event["id"]), handler=name)
                                          .on_conflict_do_nothing().returning(inbox.c.event_id))
            if first.first() is None:
                return False
            await fn(session, event)
        return True

    # ------------------------------------------------------------- state ---
    @property
    def connected(self) -> bool:
        return self.nc is not None and self.nc.is_connected and self._ready.is_set()

    async def start(self) -> None:
        self._tasks = [asyncio.create_task(self._connect(), name="bus-connect"),
                       asyncio.create_task(self._publish_loop(), name="bus-publish"),
                       asyncio.create_task(self._cleanup_loop(), name="bus-cleanup")]
        self._tasks += [asyncio.create_task(self._consume(name), name=f"bus-consume-{name}") for name in self._handlers]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.nc is not None:
            await self.nc.close()

    async def _connect(self) -> None:
        while True:
            try:
                self.nc = await nats.connect(self.url, name=self.service, max_reconnect_attempts=-1,
                                             reconnect_time_wait=2, connect_timeout=3)
                self.js = self.nc.jetstream(timeout=5)
                await self._ensure_stream()
                for pattern, callback in self._listeners:
                    await self.nc.subscribe(self.subject + pattern, cb=self._listener(callback))
                    await self.nc.subscribe(self.live + pattern, cb=self._listener(callback))
                self._ready.set()
                self._wake.set()
                log.info("connected to NATS")
                return
            except Exception as ex:
                log.warning("NATS is not reachable (%s) — will retry", ex.__class__.__name__)
                if self.nc is not None and not self.nc.is_closed:
                    await self.nc.close()
                self.nc = None
                await asyncio.sleep(2)

    @staticmethod
    def _listener(callback: Callable[[dict], None]):
        async def on_message(message) -> None:
            try:
                callback(json.loads(message.data))
            except Exception:
                log.exception("listener failed")
        return on_message

    async def _ensure_stream(self) -> None:
        config = StreamConfig(name=self.stream, subjects=[self.subject + ">"], max_age=KEEP_EVENTS.total_seconds(),
                              duplicate_window=120)
        try:
            await self.js.stream_info(self.stream)
        except NotFoundError:
            try:
                await self.js.add_stream(config)
            except BadRequestError:        # another service created it meanwhile
                await self.js.stream_info(self.stream)

    # ---------------------------------------------------------- publishing ---
    async def publish_pending(self, limit: int = 100) -> int:
        """Send unpublished outbox rows, oldest first; returns how many went out."""
        if not self.connected:
            return 0
        sent: list[UUID] = []
        async with self.db.sessions() as session, session.begin():
            rows = (await session.execute(
                select(outbox.c.id, outbox.c.type, outbox.c.payload).where(outbox.c.published_at.is_(None))
                .order_by(outbox.c.created_at, outbox.c.id).limit(limit).with_for_update(skip_locked=True))).all()
            try:
                for row in rows:
                    await self.js.publish(self.subject + row.type, json.dumps(row.payload, ensure_ascii=False).encode(),
                                          headers={"Nats-Msg-Id": str(row.id)}, timeout=5)
                    sent.append(row.id)
            except Exception as ex:
                log.warning("publishing stopped (%s); %d of %d sent", ex.__class__.__name__, len(sent), len(rows))
            if sent:
                await session.execute(update(outbox).where(outbox.c.id.in_(sent))
                                      .values(published_at=datetime.now(UTC)))
        return len(sent)

    async def _publish_loop(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=2)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                while await self.publish_pending() == 100:
                    pass
            except Exception:
                log.exception("outbox publishing failed")
                await asyncio.sleep(2)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)
            now = datetime.now(UTC)
            try:
                async with self.db.begin() as session:
                    await session.execute(delete(outbox).where(outbox.c.published_at < now - KEEP_OUTBOX))
                    await session.execute(delete(inbox).where(inbox.c.processed_at < now - KEEP_INBOX))
            except Exception:
                log.exception("cleanup failed")

    # ----------------------------------------------------------- consuming ---
    async def _consume(self, name: str) -> None:
        pattern, _ = self._handlers[name]
        await self._ready.wait()
        while True:
            try:
                sub = await self.js.pull_subscribe(self.subject + pattern, durable=f"{self.service}-{name}",
                                                   stream=self.stream)
                while True:
                    try:
                        messages = await sub.fetch(10, timeout=5)
                    except (TimeoutError, nats.errors.TimeoutError):
                        continue
                    for m in messages:
                        try:
                            await self.handle(name, json.loads(m.data))
                            await m.ack()
                        except Exception:
                            log.exception("handler %s failed — the event will be redelivered", name)
                            await m.nak(delay=5)
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                log.warning("consumer %s lost its subscription (%s) — resubscribing", name, ex.__class__.__name__)
                await asyncio.sleep(2)
