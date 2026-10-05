"""The catalog: types of equipment and furniture, their property schemas and 3D models.

    uv run uvicorn app.main:build --factory --port 8000

Settings come from the environment (twin_chassis.settings).
"""
from __future__ import annotations

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.auth import TokenVerifier

from .routes import router

SERVICE = "catalog"
TITLE = "Каталог: типы оборудования и мебели"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    return create_app(
        SERVICE,
        title=TITLE,
        routers=[router],
        settings=settings,
        verifier=verifier,
    )
