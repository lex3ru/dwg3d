"""The gateway: the single entry point of the system.

    uv run uvicorn app.main:build --factory --port 8000

Sign-in sessions (/auth/*), who is signed in (/api/me), requests passed on to
the services (/api/<service>/v1/...), events to the browser (/api/stream), assembled
answers (/api/views/*), reports (/api/reports/*), QR labels (/q/<code>).
It keeps no data of its own except the sessions.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.auth import TokenVerifier

from .config import GatewayConfig
from .oidc import Oidc
from .reports import router as reports
from .routes import router
from .sessions import Sessions
from .stream import Hub
from .views import router as views

SERVICE = "gateway"
TITLE = "Шлюз"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None, config: GatewayConfig | None = None,
          http: httpx.AsyncClient | None = None) -> FastAPI:
    config = config or GatewayConfig.from_env()

    def setup(app: FastAPI) -> None:
        state = app.state
        state.config = config
        # one client for the services and Keycloak; a slow service must not hold a browser forever
        state.http = http or httpx.AsyncClient(timeout=httpx.Timeout(60, connect=3), follow_redirects=False)
        state.oidc = Oidc(state.settings, config, state.http)
        state.sessions = Sessions(state.db, config, state.oidc, state.verifier)
        state.hub = Hub()
        state.bus.listen(">", state.hub.dispatch)

    return create_app(SERVICE, title=TITLE, routers=[router, views, reports], settings=settings, verifier=verifier,
                      setup=setup, prefix="")
