from fastapi import FastAPI

from app.core.module import Module
from app.modules.reports import dump  # задачи выгрузки и уборки архивов регистрируются сами
from app.modules.reports.routes import router


def _setup(_: FastAPI) -> None:
    dump.register_settings()


module = Module(name="reports", title="Отчёты", routers=[router], setup=_setup)
