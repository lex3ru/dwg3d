"""The ping service.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings).
"""
from __future__ import annotations

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.auth import TokenVerifier

from . import handlers
from .routes import router

SERVICE = "ping"
TITLE = "Образец сервиса: проверка связи"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    return create_app(
        SERVICE,
        title=TITLE,
        routers=[router],
        settings=settings,
        verifier=verifier,
        setup=lambda app: handlers.register(app.state.bus),
    )
