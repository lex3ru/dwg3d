"""The copilot service: an AI assistant that works through the other services' requests with the user's token.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings); TWIN_SERVICES — where the other services are;
TWIN_COPILOT_SECRET — encrypts the model's API key at rest. The model itself is set by the system administrator
(PUT /settings).
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.access import Rights
from twin_chassis.auth import TokenVerifier
from twin_chassis.client import ServiceClient, services_from_env

from . import agent
from .routes import router

SERVICE = "copilot"
TITLE = "Копилот"
DEFAULT_SERVICES = ",".join(f"{s}=http://{s}:8000" for s in (
    "access", "buildings", "import", "catalog", "assets", "people", "journal", "planning"))


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None,
          client: ServiceClient | None = None, model_http: httpx.AsyncClient | None = None) -> FastAPI:
    def setup(app: FastAPI) -> None:
        app.state.client = client or ServiceClient(
            app.state.settings, services_from_env(os.environ.get("TWIN_SERVICES", DEFAULT_SERVICES)))
        app.state.rights = Rights(app.state.client)
        app.state.model_http = model_http or agent.model_http()

    return create_app(SERVICE, title=TITLE, routers=[router], settings=settings, verifier=verifier, setup=setup)
