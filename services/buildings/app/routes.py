"""Requests of the buildings service, under /api/buildings/v1 (contracts/openapi/buildings.v1.json).

Until the access service exists (stage 2) everything here is for the system
administrator; reading is also open to other services.
"""
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from twin_chassis import Identity, Problem, emit, require_admin, require_admin_or_service, uuid7

from . import publish, storage
from .models import buildings, drawings, floor_plans, floors, pins, rooms

router = APIRouter()
MAX_FACADE = 300 * 1024 * 1024


def iso(t) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t else None


# ---------------------------------------------------------------- buildings ---
class BuildingIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=500)


class BuildingPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    version: int = Field(description="Версия, которую видел клиент")


class Site(BaseModel):
    """Where the building stands on the map."""
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    bearing: float = Field(default=0, ge=-360, le=360, description="Поворот здания, градусы")
    scale: float = Field(default=1, gt=0, le=100)


def building_json(b, counts: dict | None = None) -> dict:
    out = {"id": str(b.id), "name": b.name, "address": b.address, "site": b.site,
           "facade": {k: v for k, v in b.facade.items() if k != "key"} if b.facade else None,
           "version": b.version, "created_at": iso(b.created_at), "updated_at": iso(b.updated_at)}
    if counts is not None:
        out.update(counts)
    return out


async def _building(session, building_id: UUID, *, lock: bool = False):
    q = select(buildings).where(buildings.c.id == building_id, buildings.c.deleted_at.is_(None))
    b = (await session.execute(q.with_for_update() if lock else q)).one_or_none()
    if b is None:
        raise Problem(404, "not_found", "Здание не найдено")
    return b


def _stale(row, version: int, current: dict) -> None:
    if row.version != version:
        raise Problem(409, "version_conflict", "Данные изменил кто-то другой — обновите страницу",
                      extra={"current": current})


@router.get("/buildings", tags=["buildings"], summary="Здания")
async def list_buildings(request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(buildings).where(buildings.c.deleted_at.is_(None))
                                      .order_by(buildings.c.name, buildings.c.id))).all()
        n_floors = dict((await session.execute(select(floors.c.building_id, func.count()).where(
            floors.c.status == "active").group_by(floors.c.building_id))).all())
        n_rooms = dict((await session.execute(select(rooms.c.building_id, func.count()).where(
            rooms.c.status == "active").group_by(rooms.c.building_id))).all())
        n_drawings = dict((await session.execute(select(drawings.c.building_id, func.count())
                                                 .group_by(drawings.c.building_id))).all())
    return {"items": [building_json(b, {"floors": n_floors.get(b.id, 0), "rooms": n_rooms.get(b.id, 0),
                                        "drawings": n_drawings.get(b.id, 0)}) for b in rows]}


@router.post("/buildings", status_code=201, tags=["buildings"], summary="Создать здание")
async def create_building(body: BuildingIn, request: Request, me: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        b = (await session.execute(insert(buildings).values(
            id=uuid7(), name=body.name.strip(), address=body.address.strip(), created_by=me.sub)
            .returning(buildings))).one()
        await emit(session, "buildings.building.created", ("building", b.id), {"name": b.name}, building_id=b.id)
    return building_json(b)


@router.get("/buildings/{building_id}", tags=["buildings"], summary="Здание")
async def get_building(building_id: UUID, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        return building_json(await _building(session, building_id))


@router.patch("/buildings/{building_id}", tags=["buildings"], summary="Изменить название и адрес")
async def patch_building(building_id: UUID, body: BuildingPatch, request: Request,
                         _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id, lock=True)
        _stale(b, body.version, building_json(b))
        values = {k: v.strip() for k, v in body.model_dump(exclude={"version"}, exclude_none=True).items()}
        b = (await session.execute(update(buildings).where(buildings.c.id == building_id).values(
            **values, version=buildings.c.version + 1, updated_at=func.now()).returning(buildings))).one()
        await emit(session, "buildings.building.changed", ("building", b.id),
                   {"fields": sorted(values)}, building_id=b.id)
    return building_json(b)


@router.delete("/buildings/{building_id}", status_code=204, tags=["buildings"], summary="Удалить здание")
async def delete_building(building_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> None:
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id, lock=True)
        await session.execute(update(buildings).where(buildings.c.id == building_id).values(deleted_at=func.now()))
        await emit(session, "buildings.building.deleted", ("building", b.id), {"name": b.name}, building_id=b.id)


@router.put("/buildings/{building_id}/site", tags=["buildings"], summary="Привязать здание к карте")
async def put_site(building_id: UUID, request: Request, body: Site | None = None,
                   _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        await _building(session, building_id, lock=True)
        b = (await session.execute(update(buildings).where(buildings.c.id == building_id).values(
            site=body.model_dump() if body else None, version=buildings.c.version + 1, updated_at=func.now())
            .returning(buildings))).one()
        await emit(session, "buildings.building.changed", ("building", b.id), {"fields": ["site"]}, building_id=b.id)
    return building_json(b)


# ------------------------------------------------------------------- facade ---
class FacadeAlign(BaseModel):
    """How the detailed model sits on the building: shift (m), turn (degrees), scale."""
    dx: float = 0
    dy: float = 0
    dz: float = 0
    rotation: float = 0
    scale: float = Field(default=1, gt=0, le=1000)


@router.put("/buildings/{building_id}/facade", tags=["facade"], summary="Загрузить детальную модель фасада (GLB)")
async def put_facade(building_id: UUID, request: Request, file: UploadFile = File(...),
                     _: Identity = Depends(require_admin)) -> dict:
    data = await file.read(MAX_FACADE + 1)
    if len(data) > MAX_FACADE:
        raise Problem(413, "too_large", "Модель больше 300 МБ", title="Файл слишком большой")
    if data[:4] != b"glTF":
        raise Problem(422, "invalid", "Нужен файл GLB (двоичный glTF)", errors=[{"field": "file", "message": "не GLB"}])
    key = f"facades/{building_id}/{uuid7()}.glb"
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id, lock=True)
        await asyncio.to_thread(storage.bucket().put_bytes, key, data, "model/gltf-binary")
        facade = {**FacadeAlign().model_dump(), **{k: v for k, v in (b.facade or {}).items() if k != "key"},
                  "key": key, "name": file.filename or "facade.glb", "size": len(data)}
        b = (await session.execute(update(buildings).where(buildings.c.id == building_id).values(
            facade=facade, version=buildings.c.version + 1, updated_at=func.now()).returning(buildings))).one()
        await emit(session, "buildings.building.changed", ("building", b.id), {"fields": ["facade"]}, building_id=b.id)
    return building_json(b)


@router.patch("/buildings/{building_id}/facade", tags=["facade"], summary="Выровнять модель фасада")
async def align_facade(building_id: UUID, body: FacadeAlign, request: Request,
                       _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id, lock=True)
        if not b.facade:
            raise Problem(404, "not_found", "У здания нет модели фасада")
        b = (await session.execute(update(buildings).where(buildings.c.id == building_id).values(
            facade={**b.facade, **body.model_dump()}, version=buildings.c.version + 1, updated_at=func.now())
            .returning(buildings))).one()
        await emit(session, "buildings.building.changed", ("building", b.id), {"fields": ["facade"]}, building_id=b.id)
    return building_json(b)


@router.delete("/buildings/{building_id}/facade", status_code=204, tags=["facade"], summary="Убрать модель фасада")
async def delete_facade(building_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> None:
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id, lock=True)
        await session.execute(update(buildings).where(buildings.c.id == building_id).values(
            facade=None, version=buildings.c.version + 1, updated_at=func.now()))
        await emit(session, "buildings.building.changed", ("building", b.id), {"fields": ["facade"]}, building_id=b.id)


@router.get("/buildings/{building_id}/facade.glb", tags=["facade"], response_class=StreamingResponse,
            summary="Модель фасада")
async def get_facade(building_id: UUID, request: Request,
                     _: Identity = Depends(require_admin_or_service)) -> StreamingResponse:
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id)
    key = (b.facade or {}).get("key")
    size = await asyncio.to_thread(storage.bucket().size, key) if key else None
    if size is None:
        raise Problem(404, "not_found", "У здания нет модели фасада")
    return StreamingResponse(iterate_in_threadpool(storage.bucket().stream(key)), media_type="model/gltf-binary",
                             headers={"Content-Length": str(size), "Cache-Control": "private, no-cache"})


# ---------------------------------------------------- drawings of a building ---
class Placement(BaseModel):
    """Where a drawing sits in the building: shift (m) and turn about the vertical axis (degrees)."""
    dx: float = Field(default=0, ge=-1e5, le=1e5)
    dy: float = Field(default=0, ge=-1e5, le=1e5)
    dz: float = Field(default=0, ge=-1e4, le=1e4)
    rotation: float = Field(default=0, ge=-360, le=360)


class DrawingPatch(BaseModel):
    placement: Placement | None = None
    sort: int | None = None
    version: int


def drawing_json(d) -> dict:
    return {"id": str(d.id), "building_id": str(d.building_id), "name": d.name, "placement": d.placement,
            "build_id": str(d.build_id) if d.build_id else None, "build_n": d.build_n, "sort": d.sort,
            "version": d.version, "updated_at": iso(d.updated_at)}


@router.get("/buildings/{building_id}/drawings", tags=["drawings"], summary="Чертежи здания и их положение")
async def list_drawings(building_id: UUID, request: Request,
                        _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        await _building(session, building_id)
        rows = (await session.execute(select(drawings).where(drawings.c.building_id == building_id)
                                      .order_by(drawings.c.sort, drawings.c.created_at))).all()
    return {"items": [drawing_json(d) for d in rows]}


@router.patch("/buildings/{building_id}/drawings/{drawing_id}", tags=["drawings"],
              summary="Положение чертежа в здании")
async def patch_drawing(building_id: UUID, drawing_id: UUID, body: DrawingPatch, request: Request,
                        _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        d = (await session.execute(select(drawings).where(
            drawings.c.id == drawing_id, drawings.c.building_id == building_id).with_for_update())).one_or_none()
        if d is None:
            raise Problem(404, "not_found", "Чертёж не найден")
        _stale(d, body.version, drawing_json(d))
        values = {}
        if body.placement is not None:
            values["placement"] = body.placement.model_dump()
        if body.sort is not None:
            values["sort"] = body.sort
        d = (await session.execute(update(drawings).where(drawings.c.id == drawing_id).values(
            **values, version=drawings.c.version + 1, updated_at=func.now()).returning(drawings))).one()
        await emit(session, "buildings.building.changed", ("building", building_id),
                   {"fields": ["drawings"]}, building_id=building_id)
    return drawing_json(d)


# -------------------------------------------------------- tree, model, plan ---
def floor_json(f) -> dict:
    return {"id": str(f.id), "building_id": str(f.building_id), "drawing_id": str(f.drawing_id), "name": f.name,
            "level": f.level, "elevation": f.elevation, "height": f.height, "candidate": f.candidate,
            "status": f.status, "version": f.version}


def room_json(r, *, outline: bool = False) -> dict:
    out = {"id": str(r.id), "building_id": str(r.building_id), "floor_id": str(r.floor_id), "name": r.name,
           "number": r.number, "type": r.type, "area": round(r.area, 2), "status": r.status, "version": r.version}
    if outline:
        out.update(polygon=r.polygon, label=r.label)
    return out


def _floor_order():
    return floors.c.level.asc().nulls_last(), floors.c.elevation, floors.c.id


@router.get("/buildings/{building_id}/tree", tags=["structure"], summary="Этажи и помещения здания кратко")
async def tree(building_id: UUID, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        b = await _building(session, building_id)
        floor_rows = (await session.execute(select(floors).where(
            floors.c.building_id == building_id, floors.c.status == "active").order_by(*_floor_order()))).all()
        room_rows = (await session.execute(select(rooms).where(
            rooms.c.building_id == building_id, rooms.c.status == "active").order_by(rooms.c.name, rooms.c.idx))).all()
    by_floor: dict[UUID, list] = {}
    for r in room_rows:
        by_floor.setdefault(r.floor_id, []).append(room_json(r))
    return {"building": building_json(b),
            "floors": [{**floor_json(f), "rooms": by_floor.get(f.id, [])} for f in floor_rows]}


@router.get("/buildings/{building_id}/model", tags=["structure"],
            summary="3D-модель: по чертежу — файл модели, положение, этажи и помещения в нём")
async def model(building_id: UUID, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    """For each built drawing: `model_url` (GLB with a node per floor and per room), `placement`,
    and `result` — what the model consists of: floors (`floor_id`, `node`, level, elevation, height,
    rooms with `id`, `node`, name, type, area, label), entrances, stairs and lifts, room types."""
    async with request.app.state.db.begin() as session:
        await _building(session, building_id)
        rows = (await session.execute(select(drawings).where(drawings.c.building_id == building_id)
                                      .order_by(drawings.c.sort, drawings.c.created_at))).all()
        names = {str(i): (name, type_) for i, name, type_ in await session.execute(
            select(rooms.c.id, rooms.c.name, rooms.c.type).where(rooms.c.building_id == building_id))}
        floor_names = {str(i): name for i, name in await session.execute(
            select(floors.c.id, floors.c.name).where(floors.c.building_id == building_id))}
    out = []
    for d in rows:
        if d.build_id is None or not d.result:
            continue
        result = d.result
        for f in result.get("floors") or []:
            if f.get("floor_id") in floor_names:
                f["name"] = floor_names[f["floor_id"]]            # names changed by hand since the build
            for m in f.get("rooms") or []:
                if m.get("id") in names:
                    m["name"], m["type"] = names[m["id"]]
        out.append({**drawing_json(d), "model_url": f"/api/import/v1/builds/{d.build_id}/files/model.glb",
                    "result": result})
    return {"drawings": out}


async def _floor(session, floor_id: UUID, *, lock: bool = False):
    q = select(floors).where(floors.c.id == floor_id)
    f = (await session.execute(q.with_for_update() if lock else q)).one_or_none()
    if f is None:
        raise Problem(404, "not_found", "Этаж не найден")
    return f


@router.get("/floors/{floor_id}/plan", tags=["structure"],
            summary="План этажа: стены, проёмы, контуры помещений (координаты чертежа, м)")
async def floor_plan(floor_id: UUID, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        f = await _floor(session, floor_id)
        data = (await session.execute(select(floor_plans.c.data).where(floor_plans.c.floor_id == floor_id))).scalar()
        ids = {idx: str(i) for i, idx in await session.execute(
            select(rooms.c.id, rooms.c.idx).where(rooms.c.floor_id == floor_id, rooms.c.idx.is_not(None)))}
    if data is None:
        raise Problem(404, "not_found", "У этажа нет плана")
    for i, r in enumerate(data.get("rooms") or []):
        r["id"] = ids.get(i)
    return {"floor": floor_json(f), "plan": data}


class FloorPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: int


@router.patch("/floors/{floor_id}", tags=["structure"], summary="Переименовать этаж")
async def patch_floor(floor_id: UUID, body: FloorPatch, request: Request,
                      _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        f = await _floor(session, floor_id, lock=True)
        _stale(f, body.version, floor_json(f))
        f = (await session.execute(update(floors).where(floors.c.id == floor_id).values(
            name=body.name.strip(), manual=sorted({*f.manual, "name"}), version=floors.c.version + 1)
            .returning(floors))).one()
        await emit(session, "buildings.floor.changed", ("floor", f.id), {"fields": ["name"]},
                   building_id=f.building_id, floor_id=f.id)
    return floor_json(f)


class Points(BaseModel):
    points: list[tuple[float, float]] = Field(max_length=5000,
                                              description="Точки [x, y] в координатах чертежа этажа, м")


@router.post("/floors/{floor_id}/locate", tags=["structure"], summary="В каком помещении каждая из точек")
async def locate(floor_id: UUID, body: Points, request: Request,
                 _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        await _floor(session, floor_id)
        rows = (await session.execute(select(rooms.c.id, rooms.c.polygon).where(
            rooms.c.floor_id == floor_id, rooms.c.status == "active"))).all()
    found = await asyncio.to_thread(publish.locate, rows, [list(p) for p in body.points])
    return {"rooms": [str(r) if r else None for r in found]}


# -------------------------------------------------------------------- rooms ---
@router.get("/rooms", tags=["rooms"], summary="Поиск помещений")
async def list_rooms(request: Request, building_id: UUID, floor_id: UUID | None = None, q: str | None = None,
                     type: str | None = None, status: str = "active", limit: int = 200,
                     _: Identity = Depends(require_admin_or_service)) -> dict:
    where = [rooms.c.building_id == building_id]
    if status != "all":
        where.append(rooms.c.status == status)
    if floor_id:
        where.append(rooms.c.floor_id == floor_id)
    if type:
        where.append(rooms.c.type == type)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(rooms.c.name.ilike(like) | func.coalesce(rooms.c.number, "").ilike(like))
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(rooms).where(*where).order_by(rooms.c.name, rooms.c.id)
                                      .limit(max(1, min(limit, 500))))).all()
    return {"items": [room_json(r) for r in rows], "next": None}


class Ids(BaseModel):
    ids: list[UUID] = Field(max_length=1000)


@router.post("/rooms/batch-get", tags=["rooms"], summary="Помещения по идентификаторам")
async def batch_rooms(body: Ids, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(rooms).where(rooms.c.id.in_(body.ids or [uuid7()])))).all()
    return {"items": [room_json(r) for r in rows]}


async def _room(session, room_id: UUID, *, lock: bool = False):
    q = select(rooms).where(rooms.c.id == room_id)
    r = (await session.execute(q.with_for_update() if lock else q)).one_or_none()
    if r is None:
        raise Problem(404, "not_found", "Помещение не найдено")
    return r


@router.get("/rooms/{room_id}", tags=["rooms"], summary="Помещение с контуром")
async def get_room(room_id: UUID, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        return room_json(await _room(session, room_id), outline=True)


class RoomPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    number: str | None = Field(default=None, max_length=40)
    type: str | None = Field(default=None, max_length=40)
    version: int


@router.patch("/rooms/{room_id}", tags=["rooms"],
              summary="Название, номер и тип помещения; заданное вручную переживает новую сборку чертежа")
async def patch_room(room_id: UUID, body: RoomPatch, request: Request, _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        r = await _room(session, room_id, lock=True)
        _stale(r, body.version, room_json(r))
        values = {k: (v.strip() if isinstance(v, str) else v)
                  for k, v in body.model_dump(exclude={"version"}, exclude_unset=True).items()}
        if not values:
            return room_json(r)
        r = (await session.execute(update(rooms).where(rooms.c.id == room_id).values(
            **values, manual=sorted({*r.manual, *values}), version=rooms.c.version + 1).returning(rooms))).one()
        await emit(session, "buildings.room.changed", ("room", r.id), {"room_id": str(r.id), "fields": sorted(values)},
                   building_id=r.building_id, floor_id=r.floor_id, room_id=r.id)
    return room_json(r)


# --------------------------------------------------------------------- pins ---
class PinIn(BaseModel):
    floor_id: UUID | None = None
    kind: str = Field(default="marker", max_length=20)
    pos: tuple[float, float, float] = Field(description="Точка сцены [x, y, z], м")
    title: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=2000)


class PinPatch(BaseModel):
    pos: tuple[float, float, float] | None = None
    title: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    version: int


def pin_json(p) -> dict:
    return {"id": str(p.id), "building_id": str(p.building_id), "floor_id": str(p.floor_id) if p.floor_id else None,
            "kind": p.kind, "pos": [p.x, p.y, p.z], "title": p.title, "note": p.note, "created_by": p.created_by,
            "created_at": iso(p.created_at), "version": p.version}


@router.get("/buildings/{building_id}/pins", tags=["pins"], summary="Метки на модели")
async def list_pins(building_id: UUID, request: Request, _: Identity = Depends(require_admin_or_service)) -> dict:
    async with request.app.state.db.begin() as session:
        await _building(session, building_id)
        rows = (await session.execute(select(pins).where(pins.c.building_id == building_id)
                                      .order_by(pins.c.created_at, pins.c.id))).all()
    return {"items": [pin_json(p) for p in rows]}


@router.post("/buildings/{building_id}/pins", status_code=201, tags=["pins"], summary="Поставить метку")
async def create_pin(building_id: UUID, body: PinIn, request: Request, me: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        await _building(session, building_id)
        if body.floor_id is not None and (await _floor(session, body.floor_id)).building_id != building_id:
            raise Problem(422, "invalid", "Этаж не из этого здания",
                          errors=[{"field": "floor_id", "message": "чужой этаж"}])
        x, y, z = body.pos
        p = (await session.execute(insert(pins).values(
            id=uuid7(), building_id=building_id, floor_id=body.floor_id, kind=body.kind, x=x, y=y, z=z,
            title=body.title, note=body.note, created_by=me.sub).returning(pins))).one()
    return pin_json(p)


@router.patch("/pins/{pin_id}", tags=["pins"], summary="Изменить метку")
async def patch_pin(pin_id: UUID, body: PinPatch, request: Request, _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        p = (await session.execute(select(pins).where(pins.c.id == pin_id).with_for_update())).one_or_none()
        if p is None:
            raise Problem(404, "not_found", "Метка не найдена")
        _stale(p, body.version, pin_json(p))
        values = body.model_dump(exclude={"version", "pos"}, exclude_none=True)
        if body.pos is not None:
            values.update(zip("xyz", body.pos, strict=True))
        p = (await session.execute(update(pins).where(pins.c.id == pin_id).values(
            **values, version=pins.c.version + 1).returning(pins))).one()
    return pin_json(p)


@router.delete("/pins/{pin_id}", status_code=204, tags=["pins"], summary="Убрать метку")
async def delete_pin(pin_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> None:
    async with request.app.state.db.begin() as session:
        gone = await session.execute(delete(pins).where(pins.c.id == pin_id).returning(pins.c.id))
        if gone.first() is None:
            raise Problem(404, "not_found", "Метка не найдена")
