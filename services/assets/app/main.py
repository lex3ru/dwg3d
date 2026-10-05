"""The assets service: furniture and equipment as objects on the plan, with their properties, state and history.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings).
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.access import Rights
from twin_chassis.auth import TokenVerifier
from twin_chassis.client import ServiceClient, services_from_env

from . import handlers
from .routes import router

SERVICE = "assets"
TITLE = "Объекты: мебель и оборудование на плане"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None) -> FastAPI:
    def setup(app: FastAPI) -> None:
        # the room of a point is asked of buildings, the schema of a type of the catalog, rights of access
        default = "buildings=http://buildings:8000,catalog=http://catalog:8000,access=http://access:8000"
        app.state.client = client or ServiceClient(
            app.state.settings, services_from_env(os.environ.get("TWIN_SERVICES", default)))
        app.state.rights = Rights(app.state.client)
        handlers.register(app.state.bus, app.state.client)

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
