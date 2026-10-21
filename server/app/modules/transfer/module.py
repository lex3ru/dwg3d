from fastapi import FastAPI

from app.core.module import Module
from app.modules.transfer import package  # noqa: F401 — задача загрузки регистрируется сама
from app.modules.transfer.routes import router


def _setup(_: FastAPI) -> None:
    pass


module = Module(name="transfer", title="Перенос здания", routers=[router], setup=_setup)
