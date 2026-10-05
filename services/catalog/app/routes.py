"""Requests of the catalog, under /api/catalog/v1 (contracts/openapi/catalog.v1.json).

The catalog is read by anyone signed in and changed by the system administrator.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from twin_chassis import Identity, Problem, current_identity, emit, require_admin, uuid7

from . import glb, storage
from .models import categories, property_sets, types
from .schema import Property, check_resolved, check_values, resolve, unique_keys

router = APIRouter()


def _stale(row, version: int) -> None:
    if row.version != version:
        raise Problem(409, "version_conflict", "Запись изменил кто-то другой — обновите страницу")


async def _unused(request: Request, type_id, old: list[dict], new: list[dict]) -> None:
    """A property kept with objects may be removed, or change its kind, only while no object
    has a value for it — the assets service is asked."""
    now = {p["key"]: p for p in new if p["stored"] == "asset"}
    gone = [p for p in old if p["stored"] == "asset" and (p["key"] not in now or now[p["key"]]["kind"] != p["kind"])]
    token = request.headers.get("authorization", "").partition(" ")[2].strip()
    for p in gone:
        r = await request.app.state.client.get("assets", f"/usage?type_id={type_id}&prop={p['key']}", token=token)
        if r.status_code != 200:
            raise Problem(503, "service_unavailable",
                          "Сервис объектов не ответил — проверить, занято ли свойство, нельзя",
                          extra={"service": "assets"})
        if (n := r.json()["with_value"]) > 0:
            raise Problem(409, "in_use", f"Свойство «{p['title']}» заполнено у объектов ({n}): "
                                         "его нельзя убрать и нельзя сменить вид значения")


# --------------------------------------------------------------- categories ---
class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str = Field(default="#868e96", pattern=r"^#[0-9a-fA-F]{6}$")
    sort: int = 0


def category_json(c) -> dict:
    return {"id": str(c.id), "name": c.name, "color": c.color, "sort": c.sort}


@router.get("/categories", tags=["categories"], summary="Разделы каталога")
async def list_categories(request: Request, _: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(categories).order_by(categories.c.sort, categories.c.name))).all()
    return {"items": [category_json(c) for c in rows]}


@router.post("/categories", status_code=201, tags=["categories"], summary="Добавить раздел")
async def create_category(body: CategoryIn, request: Request, _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        c = (await session.execute(insert(categories).values(id=uuid7(), **body.model_dump())
                                   .returning(categories))).one()
    return category_json(c)


@router.patch("/categories/{category_id}", tags=["categories"], summary="Изменить раздел")
async def patch_category(category_id: UUID, body: CategoryIn, request: Request,
                         _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        c = (await session.execute(update(categories).where(categories.c.id == category_id)
                                   .values(**body.model_dump()).returning(categories))).one_or_none()
    if c is None:
        raise Problem(404, "not_found", "Раздел не найден")
    return category_json(c)


@router.delete("/categories/{category_id}", status_code=204, tags=["categories"], summary="Удалить пустой раздел")
async def delete_category(category_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> None:
    async with request.app.state.db.begin() as session:
        used = (await session.execute(select(func.count()).select_from(types)
                                      .where(types.c.category_id == category_id))).scalar_one()
        if used:
            raise Problem(409, "in_use", f"В разделе есть типы ({used}) — перенесите их в другой раздел")
        gone = await session.execute(delete(categories).where(categories.c.id == category_id)
                                     .returning(categories.c.id))
        if gone.first() is None:
            raise Problem(404, "not_found", "Раздел не найден")


# ------------------------------------------------------------ property sets ---
class SetIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    properties: list[Property] = Field(default_factory=list, max_length=100)


class SetPatch(SetIn):
    version: int


def set_json(s, used: int | None = None) -> dict:
    out = {"id": str(s.id), "name": s.name, "description": s.description, "properties": s.properties,
           "version": s.version}
    if used is not None:
        out["types"] = used
    return out


async def _sets(session) -> dict:
    return {s.id: s for s in (await session.execute(select(property_sets))).all()}


@router.get("/property-sets", tags=["property sets"], summary="Наборы свойств")
async def list_sets(request: Request, _: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(property_sets).order_by(property_sets.c.name))).all()
        using = (await session.execute(select(types.c.sets))).scalars().all()
    return {"items": [set_json(s, sum(s.id in ids for ids in using)) for s in rows]}


@router.get("/property-sets/{set_id}", tags=["property sets"], summary="Набор свойств")
async def get_set(set_id: UUID, request: Request, _: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        s = (await session.execute(select(property_sets).where(property_sets.c.id == set_id))).one_or_none()
    if s is None:
        raise Problem(404, "not_found", "Набор свойств не найден")
    return set_json(s)


@router.post("/property-sets", status_code=201, tags=["property sets"], summary="Создать набор свойств")
async def create_set(body: SetIn, request: Request, _: Identity = Depends(require_admin)) -> dict:
    unique_keys(body.properties, "в наборе")
    async with request.app.state.db.begin() as session:
        s = (await session.execute(insert(property_sets).values(
            id=uuid7(), name=body.name.strip(), description=body.description,
            properties=[p.model_dump() for p in body.properties]).returning(property_sets))).one()
    return set_json(s)


@router.patch("/property-sets/{set_id}", tags=["property sets"],
              summary="Изменить набор: меняет схему всех типов, которые его используют")
async def patch_set(set_id: UUID, body: SetPatch, request: Request, _: Identity = Depends(require_admin)) -> dict:
    unique_keys(body.properties, "в наборе")
    async with request.app.state.db.begin() as session:
        locked = select(property_sets).where(property_sets.c.id == set_id).with_for_update()
        s = (await session.execute(locked)).one_or_none()
        if s is None:
            raise Problem(404, "not_found", "Набор свойств не найден")
        _stale(s, body.version)
        new = [p.model_dump() for p in body.properties]
        changed, old_properties = new != s.properties, s.properties
        s = (await session.execute(update(property_sets).where(property_sets.c.id == set_id).values(
            name=body.name.strip(), description=body.description, properties=new,
            version=property_sets.c.version + 1, updated_at=func.now()).returning(property_sets))).one()
        if changed:
            sets = await _sets(session)
            with_set = select(types).where(types.c.sets.contains([set_id])).with_for_update()
            using = (await session.execute(with_set)).all()
            for t in using:                          # the new set must fit every type that has it
                check_resolved(t.name, resolve(t, sets))
                await _unused(request, t.id, old_properties, new)
            ids = [t.id for t in using]
            if ids:
                await session.execute(update(types).where(types.c.id.in_(ids)).values(
                    schema_version=types.c.schema_version + 1, updated_at=func.now()))
            await emit(session, "catalog.property_set.changed", ("property_set", set_id),
                       {"set_id": str(set_id), "type_ids": [str(i) for i in ids]})
    return set_json(s)


@router.delete("/property-sets/{set_id}", status_code=204, tags=["property sets"],
               summary="Удалить набор, которым никто не пользуется")
async def delete_set(set_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> None:
    async with request.app.state.db.begin() as session:
        with_set = select(types.c.name).where(types.c.sets.contains([set_id])).limit(3)
        used = (await session.execute(with_set)).scalars().all()
        if used:
            raise Problem(409, "in_use", "Набор используют типы: " + ", ".join(used))
        gone = await session.execute(delete(property_sets).where(property_sets.c.id == set_id)
                                     .returning(property_sets.c.id))
        if gone.first() is None:
            raise Problem(404, "not_found", "Набор свойств не найден")


# -------------------------------------------------------------------- types ---
class TypeIn(BaseModel):
    category_id: UUID
    name: str = Field(min_length=1, max_length=200)
    w: float = Field(gt=0, le=100, description="Ширина, м")
    d: float = Field(gt=0, le=100, description="Глубина, м")
    h: float = Field(gt=0, le=100, description="Высота, м")
    elevation: float | None = Field(default=None, ge=0, le=100, description="Высота установки по умолчанию, м")
    wall_mounted: bool = False
    shape: str = Field(default="box", max_length=40)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    container: bool = Field(default=False, description="В объект можно вкладывать другие")
    portable: bool = Field(default=False, description="Перемещать может и ответственный")
    sets: list[UUID] = Field(default_factory=list, max_length=20, description="Наборы свойств, по порядку")
    properties: list[Property] = Field(default_factory=list, max_length=100, description="Собственные свойства")
    values: dict = Field(default_factory=dict, description="Значения свойств, хранимых у типа")
    article: str | None = Field(default=None, max_length=100)
    supplier: str | None = Field(default=None, max_length=200)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="RUB", pattern=r"^[A-Z]{3}$")
    sort: int = 0


class TypePatch(TypeIn):
    version: int


def type_json(t, schema: list[dict] | None = None) -> dict:
    out = {"id": str(t.id), "category_id": str(t.category_id), "name": t.name, "size": [t.w, t.d, t.h],
           "elevation": t.elevation, "wall_mounted": t.wall_mounted, "shape": t.shape, "color": t.color,
           "model": {k: v for k, v in t.model.items() if k != "key"} if t.model else None,
           "container": t.container, "portable": t.portable, "sets": [str(s) for s in t.sets],
           "properties": t.properties, "values": t.values, "article": t.article, "supplier": t.supplier,
           "price": float(t.price) if t.price is not None else None, "currency": t.currency, "active": t.active,
           "schema_version": t.schema_version, "version": t.version, "sort": t.sort}
    if schema is not None:
        out["schema"] = schema
    return out


def _type_event(t, schema_changed: bool) -> dict:
    return {"type_id": str(t.id), "name": t.name, "category_id": str(t.category_id), "schema_version": t.schema_version,
            "schema_changed": schema_changed, "container": t.container, "portable": t.portable}


async def _checked(session, body: TypeIn) -> tuple[dict, list[dict]]:
    """The values to store for the type, and its schema — or why they do not fit."""
    if (await session.execute(select(categories.c.id).where(categories.c.id == body.category_id))).first() is None:
        raise Problem(422, "invalid", "Нет такого раздела", errors=[{"field": "category_id", "message": "не найден"}])
    sets = await _sets(session)
    missing = [str(s) for s in body.sets if s not in sets]
    if missing or len(set(body.sets)) != len(body.sets):
        raise Problem(422, "invalid", "Набор свойств не найден или указан дважды",
                      errors=[{"field": "sets", "message": ", ".join(missing) or "повтор"}])
    unique_keys(body.properties, "среди собственных свойств типа")
    values = body.model_dump()
    values["properties"] = [p.model_dump() for p in body.properties]
    row = type("Row", (), {"sets": body.sets, "properties": values["properties"]})
    schema = resolve(row, sets)
    check_resolved(body.name, schema)
    check_values(schema, body.values)
    return values, schema


@router.get("/types", tags=["types"], summary="Типы")
async def list_types(request: Request, category_id: UUID | None = None, q: str | None = None,
                     active: bool | None = True, _: Identity = Depends(current_identity)) -> dict:
    where = []
    if active is not None:
        where.append(types.c.active == active)
    if category_id:
        where.append(types.c.category_id == category_id)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(types.c.name.ilike(like) | func.coalesce(types.c.article, "").ilike(like))
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(types).where(*where).order_by(types.c.sort, types.c.name))).all()
    return {"items": [type_json(t) for t in rows]}


class Ids(BaseModel):
    ids: list[UUID] = Field(max_length=1000)


@router.post("/types/batch-get", tags=["types"], summary="Типы по идентификаторам, со схемами")
async def batch_types(body: Ids, request: Request, _: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(types).where(types.c.id.in_(body.ids or [uuid7()])))).all()
        sets = await _sets(session)
    return {"items": [type_json(t, resolve(t, sets)) for t in rows]}


async def _type(session, type_id: UUID, *, lock: bool = False):
    q = select(types).where(types.c.id == type_id)
    t = (await session.execute(q.with_for_update() if lock else q)).one_or_none()
    if t is None:
        raise Problem(404, "not_found", "Тип не найден")
    return t


@router.get("/types/{type_id}", tags=["types"], summary="Тип со схемой свойств")
async def get_type(type_id: UUID, request: Request, _: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        t = await _type(session, type_id)
        return type_json(t, resolve(t, await _sets(session)))


@router.get("/types/{type_id}/schema", tags=["types"],
            summary="Схема свойств типа: свойства наборов по порядку, затем собственные")
async def get_schema(type_id: UUID, request: Request, _: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        t = await _type(session, type_id)
        return {"type_id": str(t.id), "schema_version": t.schema_version, "container": t.container,
                "portable": t.portable, "properties": resolve(t, await _sets(session))}


@router.post("/types", status_code=201, tags=["types"], summary="Создать тип")
async def create_type(body: TypeIn, request: Request, _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        values, schema = await _checked(session, body)
        t = (await session.execute(insert(types).values(id=uuid7(), **values).returning(types))).one()
        await emit(session, "catalog.type.created", ("type", t.id), _type_event(t, True))
    return type_json(t, schema)


@router.patch("/types/{type_id}", tags=["types"], summary="Изменить тип")
async def patch_type(type_id: UUID, body: TypePatch, request: Request, _: Identity = Depends(require_admin)) -> dict:
    async with request.app.state.db.begin() as session:
        old = await _type(session, type_id, lock=True)
        _stale(old, body.version)
        values, schema = await _checked(session, body)
        values.pop("version")
        schema_changed = (values["sets"], values["properties"], values["container"], values["portable"]) != (
            old.sets, old.properties, old.container, old.portable)
        if schema_changed:
            await _unused(request, type_id, resolve(old, await _sets(session)), schema)
        t = (await session.execute(update(types).where(types.c.id == type_id).values(
            **values, version=types.c.version + 1, updated_at=func.now(),
            schema_version=types.c.schema_version + (1 if schema_changed else 0)).returning(types))).one()
        await emit(session, "catalog.type.changed", ("type", t.id), _type_event(t, schema_changed))
    return type_json(t, schema)


async def _set_active(request: Request, type_id: UUID, active: bool) -> dict:
    async with request.app.state.db.begin() as session:
        old = await _type(session, type_id, lock=True)
        if old.active == active:
            return type_json(old)
        t = (await session.execute(update(types).where(types.c.id == type_id).values(
            active=active, version=types.c.version + 1, updated_at=func.now()).returning(types))).one()
        kind = "restored" if active else "archived"
        await emit(session, f"catalog.type.{kind}", ("type", t.id), _type_event(t, False))
    return type_json(t)


@router.post("/types/{type_id}/archive", tags=["types"],
             summary="Убрать тип из выбора; объекты этого типа остаются, тип открывается по ссылке")
async def archive_type(type_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> dict:
    return await _set_active(request, type_id, False)


@router.post("/types/{type_id}/restore", tags=["types"], summary="Вернуть тип в выбор")
async def restore_type(type_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> dict:
    return await _set_active(request, type_id, True)


# ------------------------------------------------------------------- models ---
@router.put("/types/{type_id}/model", tags=["models"],
            summary="Загрузить 3D-модель типа (GLB); о подозрительном размере — предупреждение")
async def put_model(type_id: UUID, request: Request, file: UploadFile = File(...), rotation: float = 0,
                    _: Identity = Depends(require_admin)) -> dict:
    data = await file.read(glb.MAX_SIZE + 1)
    if len(data) > glb.MAX_SIZE:
        raise Problem(413, "too_large", f"Модель больше {glb.MAX_SIZE // (1024 * 1024)} МБ",
                      title="Файл слишком большой")
    if data[:4] != b"glTF":
        raise Problem(422, "invalid", "Нужен файл GLB (двоичный glTF)", errors=[{"field": "file", "message": "не GLB"}])
    key = f"models/{type_id}/{uuid7()}.glb"
    async with request.app.state.db.begin() as session:
        old = await _type(session, type_id, lock=True)
        await asyncio.to_thread(storage.bucket().put_bytes, key, data, "model/gltf-binary")
        model = {"key": key, "name": file.filename or "model.glb", "size": len(data), "rotation": rotation,
                 "bounds": glb.bounds(data), "warnings": glb.warnings(data, (old.w, old.d, old.h))}
        t = (await session.execute(update(types).where(types.c.id == type_id).values(
            model=model, version=types.c.version + 1, updated_at=func.now()).returning(types))).one()
        await emit(session, "catalog.type.changed", ("type", t.id), _type_event(t, False))
    return type_json(t)


@router.delete("/types/{type_id}/model", status_code=204, tags=["models"],
               summary="Убрать модель: тип показывается фигурой")
async def delete_model(type_id: UUID, request: Request, _: Identity = Depends(require_admin)) -> None:
    async with request.app.state.db.begin() as session:
        await _type(session, type_id, lock=True)
        t = (await session.execute(update(types).where(types.c.id == type_id).values(
            model=None, version=types.c.version + 1, updated_at=func.now()).returning(types))).one()
        await emit(session, "catalog.type.changed", ("type", t.id), _type_event(t, False))


@router.get("/types/{type_id}/model.glb", tags=["models"], response_class=StreamingResponse, summary="3D-модель типа")
async def get_model(type_id: UUID, request: Request, _: Identity = Depends(current_identity)) -> StreamingResponse:
    async with request.app.state.db.begin() as session:
        t = await _type(session, type_id)
    key = (t.model or {}).get("key")
    size = await asyncio.to_thread(storage.bucket().size, key) if key else None
    if size is None:
        raise Problem(404, "not_found", "У типа нет модели")
    return StreamingResponse(iterate_in_threadpool(storage.bucket().stream(key)), media_type="model/gltf-binary",
                             headers={"Content-Length": str(size), "Cache-Control": "private, no-cache"})
