# ruff: noqa: E501
"""Requests that count by rules: places for items in rooms, detectors by area, what the cameras see, what stands wrong.
Nothing here changes anything — the copilot (or the editor) makes a variant of the places it gets."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from twin_chassis import Identity, Problem, current_identity, forbid_guests

from . import placing
from .routes import _manages, _token, types

router = APIRouter(tags=["rules"], dependencies=[Depends(forbid_guests)])


async def _tree(request: Request, building_id: UUID) -> dict:
    r = await request.app.state.client.get("buildings", f"/buildings/{building_id}/tree", token=_token(request))
    if r.status_code != 200:
        raise Problem(503 if r.status_code >= 500 else 404, "not_found", "Здание не найдено или сервис зданий не ответил")
    return r.json()


async def _plan(request: Request, floor_id: str) -> dict:
    r = await request.app.state.client.get("buildings", f"/floors/{floor_id}/plan", token=_token(request))
    if r.status_code != 200:
        raise Problem(404, "not_found", "У этажа нет плана (здание не собрано)")
    return r.json().get("plan") or {}


async def _floor_assets(request: Request, building_id: UUID, floor_id: str) -> list[dict]:
    out, cursor = [], 0
    while cursor is not None:
        r = await request.app.state.client.get("assets", "/assets", token=_token(request),
                                               params={"building_id": str(building_id), "floor_id": floor_id, "limit": 500, "cursor": cursor})
        if r.status_code != 200:
            raise Problem(503, "service_unavailable", "Сервис объектов не ответил", extra={"service": "assets"})
        body = r.json()
        out += body["items"]
        cursor = body.get("next")
    return out


class Scope:
    """The floors and rooms a request is about: a floor, or rooms by id (on whatever floors)."""

    def __init__(self, tree: dict, floor_id: str | None, room_ids: list[str] | None):
        self.floors = {f["id"]: f for f in tree.get("floors", [])}
        self.room_type = {r["id"]: r.get("type") for f in self.floors.values() for r in f.get("rooms", [])}
        self.room_floor = {r["id"]: f["id"] for f in self.floors.values() for r in f.get("rooms", [])}
        if room_ids:
            unknown = [r for r in room_ids if r not in self.room_floor]
            if unknown:
                raise Problem(404, "not_found", f"Нет таких помещений в здании: {', '.join(unknown[:5])}")
            self.by_floor = {}
            for r in room_ids:
                self.by_floor.setdefault(self.room_floor[r], []).append(r)
        elif floor_id:
            if floor_id not in self.floors:
                raise Problem(404, "not_found", "Нет такого этажа в здании")
            self.by_floor = {floor_id: None}
        else:
            raise Problem(422, "invalid", "Укажите floor_id или room_ids")
        if sum(len(v or self.floors[f].get("rooms", [])) for f, v in self.by_floor.items()) > placing.MAX_ROOMS:
            raise Problem(422, "invalid", f"Помещений слишком много: сузьте до {placing.MAX_ROOMS}")


async def _type(request: Request, type_id: str) -> dict:
    t = (await types(request)).get(type_id)
    if t is None:
        raise Problem(404, "not_found", "Нет такого типа в каталоге")
    return t


class PlacementIn(BaseModel):
    building_id: UUID
    type_id: str
    floor_id: str | None = None
    room_ids: list[str] | None = Field(default=None, max_length=100)
    count: int = Field(1, ge=1, le=placing.MAX_ITEMS, description="сколько в каждом помещении")
    where: Literal["along_wall", "center", "corners", "grid"] = "along_wall"
    gap: float = Field(0.2, ge=0, le=5, description="м между предметами")


@router.post("/placements", summary="Места для предметов типа в помещениях: у стен, в углах, сеткой, от центра (ничего не ставит)")
async def placements(body: PlacementIn, request: Request, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, body.building_id)
    t = await _type(request, body.type_id)
    scope = Scope(await _tree(request, body.building_id), body.floor_id, body.room_ids)
    all_types = await types(request)
    rooms_out, places = [], []
    for floor_id, ids in scope.by_floor.items():
        plan = await _plan(request, floor_id)
        assets = await _floor_assets(request, body.building_id, floor_id)
        for r in placing.rooms_of(plan):
            if ids is not None and r["id"] not in ids:
                continue
            if ids is None and (scope.room_type.get(r["id"]) or "other") in placing.NOT_FURNISHED:
                continue
            try:
                got, notes = placing.place_in_room(r["poly"], plan, assets, all_types, t, body.count, body.where, body.gap)
            except placing.PlanError as ex:
                raise Problem(422, "invalid", str(ex)) from ex
            rooms_out.append({"room_id": r["id"], "name": r["name"], "floor_id": floor_id, "placed": len(got), "notes": notes})
            places += [{"floor_id": floor_id, "room_id": r["id"], "x": at[0], "y": at[1], "angle": angle} for at, angle in got]
            assets = assets + [{"x": at[0], "y": at[1], "angle": angle, "type_id": body.type_id} for at, angle in got]
    w, d, h = placing.size_of(t)
    return {"item": {"id": t["id"], "name": t["name"], "size": [w, d, h]}, "rooms": rooms_out, "places": places}


class DetectorsIn(BaseModel):
    building_id: UUID
    type_id: str = Field(description="тип извещателя (с радиусом контроля detect_radius в каталоге)")
    floor_id: str | None = None
    room_ids: list[str] | None = Field(default=None, max_length=100)


@router.post("/detectors", summary="Извещатели по площади: сколько есть, сколько нужно, где добавить (ничего не ставит)")
async def detectors(body: DetectorsIn, request: Request, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, body.building_id)
    t = await _type(request, body.type_id)
    radius = placing.value(t, "detect_radius")
    if not radius:
        raise Problem(422, "invalid", f"«{t['name']}» — не извещатель с радиусом контроля (detect_radius)")
    scope = Scope(await _tree(request, body.building_id), body.floor_id, body.room_ids)
    all_types = await types(request)
    rooms_out, places = [], []
    for floor_id, ids in scope.by_floor.items():
        plan = await _plan(request, floor_id)
        assets = await _floor_assets(request, body.building_id, floor_id)
        for r in placing.rooms_of(plan):
            if ids is not None and r["id"] not in ids:
                continue
            if ids is None and (scope.room_type.get(r["id"]) or "other") in ("stair", "lift"):
                continue
            got = placing.detectors_in_room(r["poly"], assets, all_types, radius)
            rooms_out.append({"room_id": r["id"], "name": r["name"], "floor_id": floor_id, "area": got["area"], "has": got["has"],
                              "need": got["need"], "add": len(got["add"])})
            places += [{"floor_id": floor_id, "room_id": r["id"], "x": x, "y": y, "angle": 0.0} for x, y in got["add"]]
    return {"item": {"id": t["id"], "name": t["name"], "radius": radius}, "rooms": rooms_out, "places": places,
            "rule": "каждый извещатель защищает около 0,7·π·r² пола; в помещении не меньше одного"}


@router.get("/coverage", summary="Что видят камеры этажа: доля площади каждого помещения, где лицо различимо, крупнейшие слепые места")
async def coverage(request: Request, building_id: UUID, floor_id: str, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, building_id)
    scope = Scope(await _tree(request, building_id), floor_id, None)
    plan = await _plan(request, floor_id)
    assets = await _floor_assets(request, building_id, floor_id)
    all_types = await types(request)
    rooms = placing.rooms_of(plan)
    out = placing.cameras_in_rooms(rooms, assets, all_types)
    for x in out:
        x["type"] = scope.room_type.get(x["room_id"])
    return {"floor_id": floor_id, "cameras": sum(1 for a in assets if placing.camera_params(a, all_types.get(a.get("type_id")))),
            "rooms": out, "note": "приближённо: обзор режут только стены между помещениями"}


@router.get("/checks", summary="Что стоит не так на этаже: в проходах и дверях, на перегородках, друг на друге, вне стен; пустые помещения; плохо просматриваемые; узкие двери")
async def checks(request: Request, building_id: UUID, floor_id: str, limit: int = 50, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, building_id)
    scope = Scope(await _tree(request, building_id), floor_id, None)
    plan = await _plan(request, floor_id)
    assets = await _floor_assets(request, building_id, floor_id)
    all_types = await types(request)
    rooms = placing.rooms_of(plan)
    return {"floor_id": floor_id, **placing.check_floor(rooms, scope.room_type, plan, assets, all_types, max(1, min(limit, 500)))}
