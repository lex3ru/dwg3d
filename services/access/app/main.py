"""The access service: who may do what in which building, floor, room, object.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings). The automatic grants
are checked against the people and assets services on start and every
TWIN_RECONCILE_S seconds (default 600).
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.auth import TokenVerifier
from twin_chassis.client import ServiceClient, services_from_env

from . import handlers
from .reconcile import reconcile
from .routes import router

SERVICE = "access"
TITLE = "Доступ: права по областям"
log = logging.getLogger("twin.access")


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None, reconcile_s: float | None = None) -> FastAPI:
    every = reconcile_s if reconcile_s is not None else float(os.environ.get("TWIN_RECONCILE_S", "600"))

    def setup(app: FastAPI) -> None:
        app.state.client = client or ServiceClient(app.state.settings, services_from_env(os.environ.get(
            "TWIN_SERVICES", "people=http://people:8000,assets=http://assets:8000")))
        handlers.register(app.state.bus)
        app.state.reconcile = lambda: reconcile(app.state.db, app.state.client)

        async def regularly() -> None:
            await asyncio.sleep(15)                          # the neighbours are starting too
            while True:
                try:
                    await app.state.reconcile()
                except Exception as ex:
                    log.warning("reconciliation skipped: %s", ex)
                await asyncio.sleep(every)

        inner = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            task = asyncio.create_task(regularly(), name="access-reconcile")
            try:
                async with inner(app):
                    yield
            finally:
                task.cancel()

        app.router.lifespan_context = lifespan

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
