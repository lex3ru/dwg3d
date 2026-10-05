"""The import service: uploaded drawings, the build queue, the files of builds.

    uv run uvicorn app.main:build --factory --port 8000

The builds themselves run in a separate process: python -m app.worker.
Settings come from the environment (twin_chassis.settings, app/storage.py).
"""
from __future__ import annotations

from fastapi import FastAPI
from twin_chassis import Settings, create_app
from twin_chassis.auth import TokenVerifier

from .routes import router

SERVICE = "import"
TITLE = "Импорт чертежей"


def build(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    return create_app(
        SERVICE,
        title=TITLE,
        routers=[router],
        settings=settings,
        verifier=verifier,
    )
