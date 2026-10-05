"""The people service: the directory of people and which account is whose.

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

from .routes import router

SERVICE = "people"
TITLE = "Люди: справочник"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None) -> FastAPI:
    def setup(app: FastAPI) -> None:
        # whom the directory may be kept by is asked of the access service
        app.state.client = client or ServiceClient(
            app.state.settings, services_from_env(os.environ.get("TWIN_SERVICES", "access=http://access:8000")))
        app.state.rights = Rights(app.state.client)

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
