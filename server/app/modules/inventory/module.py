from fastapi import FastAPI

from app.core import search
from app.core.module import Module
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.inventory import api
from app.modules.inventory.routes import qr, router


def _setup(_: FastAPI) -> None:
    api.register_settings()
    # тип, по которому есть учёт, не удаляется — только в архив (5.2.2)
    catalog.on_usage(api.type_usage)
    # помещения объединили — имущество переходит к продолжающему (5.1.6 п. 3)
    building.on_rooms_continued(api.rooms_continued)
    building.on_building_deleted(api.building_guard)
    search.register(api.search_units)


module = Module(name="inventory", title="Учёт имущества", routers=[router, qr], setup=_setup)
