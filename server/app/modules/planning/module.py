from fastapi import FastAPI

from app.core.module import Module
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.planning import api
from app.modules.planning.routes import router


def _setup(_: FastAPI) -> None:
    # тип, который стоит на плане, не удаляется — только в архив (5.2.2)
    catalog.on_usage(api.type_usage)
    # помещения объединили, разделили, переочертили — предметы следуют за ними (5.1.6)
    building.on_rooms_continued(api.rooms_continued)
    building.on_plan_saved(api.plan_saved)
    building.guard_floor_delete(api.floor_guard)


module = Module(name="planning", title="Планировка", routers=[router], setup=_setup)
