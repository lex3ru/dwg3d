"""A service = create_app(name, routers) + its own tables and handlers."""
from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from . import errors, events, log
from .auth import TokenVerifier
from .bus import Bus
from .db import Database
from .settings import Settings


def create_app(service: str, *, title: str, routers: list[APIRouter] = (), settings: Settings | None = None,
               verifier: TokenVerifier | None = None, setup: Callable[[FastAPI], None] | None = None,
               prefix: str | None = None) -> FastAPI:
    """`routers` are mounted under /api/<service>/v1 (the gateway passes its own
    `prefix`); `setup(app)` registers event handlers on app.state.bus and
    anything else before the start."""
    settings = settings or Settings.from_env(service)
    log.setup(service)
    events.configure(service, settings.contracts)
    db = Database(settings.database_url)
    bus = Bus(service, settings.nats_url, db, settings.bus_prefix)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await bus.start()
        try:
            yield
        finally:
            await bus.stop()
            await db.close()

    docs = f"/api/{service}/v1" if prefix is None else "/api"
    prefix = f"/api/{service}/v1" if prefix is None else prefix
    app = FastAPI(title=title, version="1", lifespan=lifespan, openapi_url=f"{docs}/openapi.json",
                  docs_url=f"{docs}/docs", redoc_url=None)
    app.state.settings, app.state.db, app.state.bus = settings, db, bus
    app.state.verifier = verifier or TokenVerifier(settings.oidc_issuer, settings.oidc_internal,
                                                   settings.oidc_client_id)
    errors.install(app)
    app.add_middleware(log.RequestLog)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"service": service, "ok": True, "db": await db.ok(), "nats": bus.connected}

    for router in routers:
        app.include_router(router, prefix=prefix)
    if setup is not None:
        setup(app)
    return app
