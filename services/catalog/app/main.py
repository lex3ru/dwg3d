"""The catalog: types of equipment and furniture, their property schemas and 3D models.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings).
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.auth import TokenVerifier
from twin_chassis.client import ServiceClient, services_from_env

from .routes import router

SERVICE = "catalog"
TITLE = "Каталог: типы оборудования и мебели"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None) -> FastAPI:
    def setup(app: FastAPI) -> None:
        # whether a property has values at objects is asked of the assets service
        app.state.client = client or ServiceClient(
            app.state.settings, services_from_env(os.environ.get("TWIN_SERVICES", "assets=http://assets:8000")))

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
