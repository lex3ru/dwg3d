from fastapi import FastAPI

from app.core.module import Module
from app.modules.calc import cameras, lighting  # noqa: F401 — расчёты регистрируются сами
from app.modules.calc.routes import router


def _setup(_: FastAPI) -> None:
    pass


module = Module(name="calc", title="Расчёты", routers=[router], setup=_setup)
