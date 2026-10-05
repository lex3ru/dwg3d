"""The buildings service: buildings, their floors and rooms with ids that outlive a new drawing.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings).
"""
from __future__ import annotations

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.access import Rights
from twin_chassis.auth import TokenVerifier
from twin_chassis.client import ServiceClient

from . import handlers
from .routes import router

SERVICE = "buildings"
TITLE = "Здание: этажи и помещения"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None) -> FastAPI:
    def setup(app: FastAPI) -> None:
        # how this service calls others (the import service, for the results of builds)
        app.state.client = client or ServiceClient(app.state.settings, handlers.services())
        handlers.register(app.state.bus, app.state.client)
        app.state.rights = Rights(app.state.client)

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
