"""The journal: the feed of events of every service, as they happened.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings); TWIN_JOURNAL_KEEP_DAYS —
how long events are kept (default 1825, five years); older ones are removed daily.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy import delete
from twin_chassis import Settings, create_app
from twin_chassis.access import Rights
from twin_chassis.auth import TokenVerifier
from twin_chassis.client import ServiceClient, services_from_env

from . import handlers
from .models import events
from .routes import router

SERVICE = "journal"
TITLE = "Журнал"
log = logging.getLogger("twin.journal")


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None, keep_days: float | None = None) -> FastAPI:
    days = keep_days if keep_days is not None else float(os.environ.get("TWIN_JOURNAL_KEEP_DAYS", "1825"))
    keep = timedelta(days=days)

    def setup(app: FastAPI) -> None:
        # whose areas are whose is asked of the access service, with the reader's own token
        app.state.client = client or ServiceClient(
            app.state.settings, services_from_env(os.environ.get("TWIN_SERVICES", "access=http://access:8000")))
        app.state.rights = Rights(app.state.client)
        app.state.keep = keep
        handlers.register(app.state.bus)

        async def forget_old() -> int:
            """Remove what is older than kept; returns how many."""
            async with app.state.db.begin() as session:
                gone = await session.execute(delete(events).where(events.c.time < datetime.now(UTC) - app.state.keep))
            return gone.rowcount or 0

        async def daily() -> None:
            while True:
                try:
                    gone = await forget_old()
                    if gone:
                        log.info("removed %d events older than %s", gone, app.state.keep)
                except Exception:
                    log.exception("could not remove old events")
                await asyncio.sleep(24 * 3600)

        app.state.forget_old = forget_old
        inner = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            task = asyncio.create_task(daily(), name="journal-forget")
            try:
                async with inner(app):
                    yield
            finally:
                task.cancel()

        app.router.lifespan_context = lifespan

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
