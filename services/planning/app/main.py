"""The planning service: variants of placing the objects of a building — made, compared, applied.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings); TWIN_SERVICES — where access, assets, catalog and buildings are.
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
from .rules import router as rules

SERVICE = "planning"
TITLE = "Проектирование"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None) -> FastAPI:
    def setup(app: FastAPI) -> None:
        app.state.client = client or ServiceClient(app.state.settings, services_from_env(os.environ.get(
            "TWIN_SERVICES", "access=http://access:8000,assets=http://assets:8000,catalog=http://catalog:8000,buildings=http://buildings:8000")))
        app.state.rights = Rights(app.state.client)
        handlers.register(app.state.bus)

    return create_app(SERVICE, title=TITLE, routers=[router, rules], settings=settings, verifier=verifier, setup=setup)
