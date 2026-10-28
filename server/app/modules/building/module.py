from fastapi import FastAPI

from app.core.module import Module
from app.modules.access import api as access
from app.modules.building import api, drawings
from app.modules.building.routes import router
from app.modules.files import api as files
from app.modules.system import api as system


def _setup(_: FastAPI) -> None:
    # доступ узнаёт названия зданий и чистит выдачи удалённого здания
    access.set_building_directory(api.Directory())
    api.on_building_deleted(access.revoke_building)
    # подложка плана — тем, кому видно здание, и гостю по ссылке (5.7.2); исходный чертёж —
    # без гостя (R-018 п. 3)
    files.on_file_access(api.is_underlay_file)
    files.on_file_access(drawings.is_drawing_file)
    # подложка этажа через /api/files — до лимита из настроек (7.3 п. 4)
    files.on_upload_limit("underlay", lambda session: system.upload_limit(session, "underlay"))


module = Module(name="building", title="Здание и план", routers=[router], setup=_setup)
