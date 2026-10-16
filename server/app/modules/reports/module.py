from fastapi import FastAPI

from app.core.module import Module
from app.modules.reports import dump  # noqa: F401 — задача полной выгрузки регистрируется сама
from app.modules.reports.routes import router


def _setup(_: FastAPI) -> None:
    pass


module = Module(name="reports", title="Отчёты", routers=[router], setup=_setup)
