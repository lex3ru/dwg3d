from fastapi import FastAPI

from app.core.module import Module
from app.modules.building import api as building
from app.modules.inventory import api as inventory
from app.modules.link import api
from app.modules.link.routes import router
from app.modules.planning import api as planning


def _setup(_: FastAPI) -> None:
    # перенос связанного предмета в другое помещение — перемещение в учёте (С13)
    planning.on_items_changed(api.items_changed)
    # единица ушла документом — её предмет уходит с плана (5.5)
    inventory.on_units_changed(api.units_changed)
    # план сохранили с новыми очертаниями — учтённое переходит туда, где стоит его предмет
    building.on_plan_saved(api.plan_saved)


module = Module(name="link", title="Связь планировки и учёта", routers=[router], setup=_setup)
