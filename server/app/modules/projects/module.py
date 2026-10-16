from fastapi import FastAPI

from app.core.module import Module
from app.modules.catalog import api as catalog
from app.modules.projects import api
from app.modules.projects.routes import router


def _setup(_: FastAPI) -> None:
    # тип, который проект ставит, не удаляется из каталога — только в архив (5.2.2)
    catalog.on_usage(api.type_usage)


module = Module(name="projects", title="Проекты", routers=[router], setup=_setup)
