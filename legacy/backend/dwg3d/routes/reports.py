"""Equipment specifications (JSON or Excel) and checks of the engineering layers."""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, HTTPException, Response

from .. import access, auth, db, reports
from . import common

router = APIRouter()
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(data: bytes, name: str) -> Response:
    quoted = urllib.parse.quote(name + ".xlsx")
    return Response(data, media_type=XLSX, headers={
        "Content-Disposition": f"attachment; filename=\"specification.xlsx\"; filename*=UTF-8''{quoted}"})


@router.get("/api/reports/equipment")
def equipment_report(project: str | None = None, layer: str | None = None, by: str = "floor",
                     format: str = "json"):
    """Specification of one project (per floor, or room by room with by=room) or
    of all projects (per project); of one layer with `layer`; format=xlsx for Excel."""
    if format not in ("json", "xlsx"):
        raise HTTPException(400, "format: json или xlsx")
    if by not in ("floor", "room") or (by == "room" and project is None):
        raise HTTPException(400, "by: floor или room (room — только для проекта)")
    with db.session() as s:
        if project is not None:
            common.project(s, project)
        if layer is not None and (project is None or common.layer_of(s, project, layer) is None):
            raise HTTPException(404, "Слой не найден")
        me = auth.current.get()
        rep = (reports.by_room(s, project, layer, me, access.visible_layers(me)) if by == "room"
               else reports.equipment(s, project, layer, me, access.visible_layers(me)))
    if format == "json":
        return rep
    if by == "room":
        return _xlsx(reports.rooms_to_xlsx(rep), f"Спецификация по помещениям — {rep['project']['name']}")
    return _xlsx(reports.to_xlsx(rep), f"Спецификация — {rep['project']['name']}" if project else "Сводная спецификация")


@router.get("/api/projects/{pid}/checks")
def project_checks(pid: str):
    """Problems of the engineering layers: rooms short of fire detectors."""
    with db.session() as s:
        common.project(s, pid)
        return {"fire": reports.fire_check(s, pid, auth.current.get())}
