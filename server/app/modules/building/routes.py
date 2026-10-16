import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.core.auth import CurrentActor
from app.core.db import DB
from app.core.errors import AppError
from app.modules.building import api
from app.modules.building.plan import Plan

router = APIRouter(prefix="/api", tags=["building"])


def _full(session: DB, actor: CurrentActor, building_id: uuid.UUID) -> dict[str, Any]:
    building = api.get_building(session, actor, building_id)
    counts = api._counts(session, [building.id])[building.id]
    return {**api.building_view(building, counts),
            "floors": [api.floor_view(session, f) for f in api.floors(session, building.id)],
            "floor_count": counts[0]}


@router.get("/buildings")
def list_buildings(actor: CurrentActor, session: DB, archived: bool = False) -> dict[str, Any]:
    return {"items": api.list_buildings(session, actor, archived)}


class BuildingIn(BaseModel):
    name: str = Field(max_length=200)
    address: str = Field(default="", max_length=300)


@router.post("/buildings", status_code=201)
def create_building(body: BuildingIn, actor: CurrentActor, session: DB) -> dict[str, Any]:
    building = api.create_building(session, actor, body.name, body.address)
    return _full(session, actor, building.id)


@router.get("/buildings/{building_id}")
def get_building(building_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return _full(session, actor, building_id)


class BuildingPatch(BaseModel):
    version: int
    name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)


@router.patch("/buildings/{building_id}")
def update_building(building_id: uuid.UUID, body: BuildingPatch, actor: CurrentActor,
                    session: DB) -> dict[str, Any]:
    api.update_building(session, actor, building_id, body.version, body.name, body.address)
    return _full(session, actor, building_id)


@router.post("/buildings/{building_id}/archive")
def archive(building_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    api.set_archived(session, actor, building_id, True)
    return _full(session, actor, building_id)


@router.post("/buildings/{building_id}/unarchive")
def unarchive(building_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    api.set_archived(session, actor, building_id, False)
    return _full(session, actor, building_id)


@router.delete("/buildings/{building_id}", status_code=204)
def delete_building(building_id: uuid.UUID, actor: CurrentActor, session: DB) -> None:
    api.delete_building(session, actor, building_id)


class FloorIn(BaseModel):
    name: str = Field(max_length=100)
    elevation: float | None = None
    height: float = 3300
    copy_bearing_from: uuid.UUID | None = None


@router.post("/buildings/{building_id}/floors", status_code=201)
def add_floor(building_id: uuid.UUID, body: FloorIn, actor: CurrentActor, session: DB
              ) -> dict[str, Any]:
    floor = api.add_floor(session, actor, building_id, body.name, body.elevation, body.height,
                          body.copy_bearing_from)
    return api.floor_view(session, floor)


class FloorPatch(BaseModel):
    version: int
    name: str | None = Field(default=None, max_length=100)
    elevation: float | None = None
    height: float | None = None


@router.patch("/floors/{floor_id}")
def update_floor(floor_id: uuid.UUID, body: FloorPatch, actor: CurrentActor, session: DB
                 ) -> dict[str, Any]:
    floor = api.update_floor(session, actor, floor_id, body.version, body.name, body.elevation,
                             body.height)
    return api.floor_view(session, floor)


@router.delete("/floors/{floor_id}", status_code=204)
def delete_floor(floor_id: uuid.UUID, actor: CurrentActor, session: DB) -> None:
    api.delete_floor(session, actor, floor_id)


@router.get("/floors/{floor_id}/plan")
def get_plan(floor_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return api.plan_view(session, actor, api.get_floor(session, actor, floor_id))


class PlanIn(BaseModel):
    plan: Plan
    merges: list[dict[str, Any]] = []


@router.post("/floors/{floor_id}/plan/check")
def check_plan(floor_id: uuid.UUID, body: PlanIn, actor: CurrentActor, session: DB
               ) -> dict[str, Any]:
    return api.check_plan(session, actor, floor_id, body.plan, body.merges)


@router.post("/floors/{floor_id}/plan/fix")
def fix_plan(floor_id: uuid.UUID, body: PlanIn, actor: CurrentActor, session: DB
             ) -> dict[str, Any]:
    api.get_floor(session, actor, floor_id)
    return api.fix_plan(actor, body.plan)


class PlanSave(PlanIn):
    plan_version: int
    confirm: bool = False


@router.put("/floors/{floor_id}/plan")
def save_plan(floor_id: uuid.UUID, body: PlanSave, actor: CurrentActor, session: DB
              ) -> dict[str, Any]:
    return api.save_plan(session, actor, floor_id, body.plan, body.plan_version, body.merges,
                         body.confirm)


class LiftIn(BaseModel):
    name: str | None = Field(default=None, max_length=50)
    x: float | None = None
    y: float | None = None
    w: float | None = None
    d: float | None = None
    angle: float | None = None
    door_side: int | None = Field(default=None, ge=0, le=3)
    floor_ids: list[uuid.UUID] | None = None
    stop_ids: list[uuid.UUID] | None = None


@router.post("/buildings/{building_id}/lifts", status_code=201)
def create_lift(building_id: uuid.UUID, body: LiftIn, actor: CurrentActor, session: DB
                ) -> dict[str, Any]:
    values = body.model_dump(exclude_none=True)
    if "x" not in values or "y" not in values or not values.get("floor_ids"):
        raise AppError("Укажите место шахты и этажи, через которые она проходит.")
    return api.lift_view(api.create_lift(session, actor, building_id, values))


@router.patch("/lifts/{lift_id}")
def update_lift(lift_id: uuid.UUID, body: LiftIn, actor: CurrentActor, session: DB
                ) -> dict[str, Any]:
    return api.lift_view(api.update_lift(session, actor, lift_id,
                                         body.model_dump(exclude_none=True)))


@router.delete("/lifts/{lift_id}", status_code=204)
def delete_lift(lift_id: uuid.UUID, actor: CurrentActor, session: DB) -> None:
    api.delete_lift(session, actor, lift_id)


@router.get("/floors/{floor_id}/export.{fmt}")
def export_floor(floor_id: uuid.UUID, fmt: str, actor: CurrentActor, session: DB,
                 paper: str = "A4", orientation: str = "landscape", scale: int | None = None
                 ) -> Response:
    if fmt not in ("pdf", "dxf"):
        raise AppError("Выгрузка — в PDF или DXF.")
    data, name = api.export_floor(session, actor, floor_id, fmt, paper, orientation, scale)
    media = "application/pdf" if fmt == "pdf" else "application/dxf"
    disposition = "inline" if fmt == "pdf" else "attachment"
    return Response(data, media_type=media, headers={
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}"})
