"""Requests of the planning service, under /api/planning/v1 (contracts/openapi/planning.v1.json).

Variants of placing objects belong to a building and are its administrators' tool: every request needs the
right to manage the building. The fact — the objects, the catalog — is asked of the assets and catalog
services with the user's own token, so a variant sees what its author sees; applying a variant is done by
the assets service on the user's behalf, with the objects' history. A guest by a link has no business
here at all (403 `guest`).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select, update
from twin_chassis import Identity, Problem, current_identity, emit, forbid_guests, uuid7

from . import overlay
from .models import variant_ops, variants

router = APIRouter(dependencies=[Depends(forbid_guests)])
FACT = "fact"


def iso(t) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t else None


def op_json(o) -> dict:
    return {"id": str(o.id), "op": o.op, "asset_id": str(o.asset_id) if o.asset_id else None,
            "base_version": o.base_version, "data": o.data, "sort": o.sort}


def variant_json(v, ops: list | None = None) -> dict:
    out = {"id": str(v.id), "building_id": str(v.building_id), "name": v.name,
           "based_on": str(v.based_on) if v.based_on else None, "status": v.status, "stale": v.stale,
           "stale_reasons": v.stale_reasons, "last_result": v.last_result, "created_by": v.created_by,
           "created_at": iso(v.created_at), "updated_at": iso(v.updated_at), "applied_at": iso(v.applied_at),
           "version": v.version}
    if ops is not None:
        out["ops"] = [op_json(o) for o in ops]
        out["counts"] = {k: sum(1 for o in ops if o.op == k) for k in ("add", "move", "change", "remove")}
    return out


def _token(request: Request) -> str:
    return request.headers.get("authorization", "").partition(" ")[2].strip()


async def _manages(request: Request, me: Identity, building_id: UUID) -> None:
    await request.app.state.rights.require(request, me, "manage", [("building", building_id)], what="Здание не найдено")


async def _variant(request: Request, me: Identity, variant_id: UUID, *, lock: bool = False, session=None):
    async def load(s):
        q = select(variants).where(variants.c.id == variant_id)
        return (await s.execute(q.with_for_update() if lock else q)).one_or_none()
    if session is not None:
        v = await load(session)
    else:
        async with request.app.state.db.begin() as s:
            v = await load(s)
    if v is None:
        raise Problem(404, "not_found", "Вариант не найден")
    await _manages(request, me, v.building_id)
    return v


async def _ops(session, variant_id: UUID) -> list:
    return (await session.execute(select(variant_ops).where(variant_ops.c.variant_id == variant_id)
                                  .order_by(variant_ops.c.sort, variant_ops.c.id))).all()


# ------------------------------------------------------------- the fact ---
async def fact(request: Request, building_id: UUID) -> list[dict]:
    """The objects of the building that stand on a floor, as the assets service shows them to the user."""
    client, out, cursor = request.app.state.client, [], 0
    while cursor is not None:
        r = await client.request("GET", "assets", "/assets", token=_token(request),
                                 params={"building_id": str(building_id), "limit": 500, "cursor": cursor})
        if r.status_code != 200:
            raise Problem(503, "service_unavailable", "Сервис объектов не ответил", extra={"service": "assets"})
        body = r.json()
        out += body["items"]
        cursor = body.get("next")
    return out


async def types(request: Request) -> dict[str, dict]:
    """The catalog's types with their prices; without the catalog — none (names come from the objects)."""
    out: dict[str, dict] = {}
    for active in ("true", "false"):
        r = await request.app.state.client.request("GET", "catalog", "/types", token=_token(request),
                                                   params={"active": active})
        if r.status_code == 200:
            out.update({t["id"]: t for t in r.json()["items"]})
    return out


async def products(request: Request) -> dict[str, dict]:
    """The makes and models of the catalog's types with their list prices; without the catalog — none."""
    r = await request.app.state.client.request("GET", "catalog", "/products", token=_token(request))
    return {p["id"]: p for p in r.json()["items"]} if r.status_code == 200 else {}


def _rows(ops: list) -> list[dict]:
    return [{"id": o.id, "op": o.op, "asset_id": o.asset_id, "base_version": o.base_version, "data": o.data,
             "sort": o.sort} for o in ops]


# -------------------------------------------------------------- variants ---
class VariantIn(BaseModel):
    building_id: UUID
    name: str = Field(min_length=1, max_length=200)
    based_on: UUID | None = Field(default=None, description="Скопировать операции другого варианта; иначе — от факта")


class VariantPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: int


@router.get("/variants", tags=["variants"], summary="Варианты расстановки в здании")
async def list_variants(request: Request, building_id: UUID, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, building_id)
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(variants).where(variants.c.building_id == building_id)
                                      .order_by(variants.c.created_at, variants.c.id))).all()
        ops = (await session.execute(select(variant_ops).where(
            variant_ops.c.variant_id.in_([v.id for v in rows] or [uuid7()])))).all()
    by: dict = {}
    for o in ops:
        by.setdefault(o.variant_id, []).append(o)
    return {"items": [variant_json(v, by.get(v.id, [])) for v in rows]}


@router.post("/variants", status_code=201, tags=["variants"], summary="Создать вариант: от факта или копией другого")
async def create_variant(body: VariantIn, request: Request, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, body.building_id)
    async with request.app.state.db.begin() as session:
        source = []
        if body.based_on is not None:
            src = (await session.execute(select(variants).where(variants.c.id == body.based_on))).one_or_none()
            if src is None or src.building_id != body.building_id:
                raise Problem(422, "invalid", "Нет такого варианта в этом здании",
                              errors=[{"field": "based_on", "message": "не найден"}])
            source = await _ops(session, src.id)
        v = (await session.execute(insert(variants).values(
            id=uuid7(), building_id=body.building_id, name=body.name.strip(), based_on=body.based_on,
            created_by=me.sub).returning(variants))).one()
        for o in source:
            await session.execute(insert(variant_ops).values(
                id=uuid7(), variant_id=v.id, op=o.op, asset_id=o.asset_id, base_version=o.base_version,
                data=o.data, sort=o.sort))
        await emit(session, "planning.variant.created", ("variant", v.id),
                   {"variant_id": str(v.id), "name": v.name, "based_on": str(v.based_on) if v.based_on else None},
                   building_id=v.building_id)
        return variant_json(v, await _ops(session, v.id))


@router.get("/variants/{variant_id}", tags=["variants"],
            summary="Вариант с операциями; у каждой — устарела ли она (объект изменён после неё)")
async def get_variant(variant_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    v = await _variant(request, me, variant_id)
    objects = await fact(request, v.building_id)
    async with request.app.state.db.begin() as session:
        ops = await _ops(session, variant_id)
        laid = overlay.lay(objects, _rows(ops))
        conflicts = {o["op_id"] or "": o["conflict"] for o in laid.values() if o["conflict"]}
        by_asset = {o["asset_id"]: o["conflict"] for o in laid.values() if o["conflict"] and o["asset_id"]}
        if v.stale and not by_asset and not conflicts:          # every operation is against the present fact
            v = (await session.execute(update(variants).where(variants.c.id == variant_id).values(
                stale=False, stale_reasons=[]).returning(variants))).one()
    out = variant_json(v, ops)
    for o in out["ops"]:
        o["conflict"] = by_asset.get(o["asset_id"]) if o["asset_id"] else None
        if o["conflict"] is None and o["id"] in conflicts:
            o["conflict"] = conflicts[o["id"]]
    return out


@router.patch("/variants/{variant_id}", tags=["variants"], summary="Переименовать вариант")
async def patch_variant(variant_id: UUID, body: VariantPatch, request: Request,
                        me: Identity = Depends(current_identity)) -> dict:
    await _variant(request, me, variant_id)
    async with request.app.state.db.begin() as session:
        v = await _variant(request, me, variant_id, lock=True, session=session)
        if v.version != body.version:
            raise Problem(409, "version_conflict", "Вариант изменил кто-то другой", extra={"current": variant_json(v)})
        v = (await session.execute(update(variants).where(variants.c.id == variant_id).values(
            name=body.name.strip(), version=variants.c.version + 1, updated_at=func.now()).returning(variants))).one()
        return variant_json(v, await _ops(session, variant_id))


@router.delete("/variants/{variant_id}", status_code=204, tags=["variants"], summary="Удалить вариант")
async def delete_variant(variant_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> None:
    v = await _variant(request, me, variant_id)
    async with request.app.state.db.begin() as session:
        await session.execute(delete(variants).where(variants.c.id == variant_id))
        await emit(session, "planning.variant.deleted", ("variant", v.id), {"variant_id": str(v.id), "name": v.name},
                   building_id=v.building_id)


# ---------------------------------------------------------------- edits ---
class Edit(BaseModel):
    kind: Literal["place", "move", "remove", "note"]
    asset_id: UUID | None = Field(default=None, description="Существующий объект")
    op_id: UUID | None = Field(default=None, description="Или объект, добавленный этим вариантом")
    version: int | None = Field(default=None, description="Версия объекта, против которой сделана правка")
    type_id: UUID | None = None
    product_id: UUID | None = Field(default=None, description="Марка и модель нового объекта, если известна")
    floor_id: UUID | None = None
    x: float | None = None
    y: float | None = None
    angle: float | None = None
    inventory_no: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=2000)


class Edits(BaseModel):
    edits: list[Edit] = Field(min_length=1, max_length=500)


def _place(e: Edit) -> dict:
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in
            (("floor_id", e.floor_id), ("x", e.x), ("y", e.y), ("angle", e.angle)) if v is not None}


@router.post("/variants/{variant_id}/edits", tags=["variants"],
             summary="Правки варианта из редактора: поставить, переместить, убрать, примечание; ответ — их результат")
async def edit_variant(variant_id: UUID, body: Edits, request: Request, me: Identity = Depends(current_identity)) -> dict:
    """An existing object gets one operation of each kind at most (the place moves, the note changes); one added by
    the variant is its `add` operation itself. Every result is the operation it became (`op_id`); `null` — removed."""
    await _variant(request, me, variant_id)
    results = []
    async with request.app.state.db.begin() as session:
        v = await _variant(request, me, variant_id, lock=True, session=session)
        if v.status != "draft":
            raise Problem(409, "applied", "Вариант уже применён — сделайте новый")
        top = (await session.execute(select(func.max(variant_ops.c.sort)).where(
            variant_ops.c.variant_id == variant_id))).scalar() or 0

        async def mine(op_id: UUID):
            o = (await session.execute(select(variant_ops).where(
                variant_ops.c.id == op_id, variant_ops.c.variant_id == variant_id, variant_ops.c.op == "add"))).one_or_none()
            if o is None:
                raise Problem(422, "invalid", "Нет такого добавленного объекта", errors=[{"field": "op_id", "message": "нет"}])
            return o

        async def upsert(kind: str, e: Edit, data: dict) -> UUID:
            nonlocal top
            found = (await session.execute(select(variant_ops).where(
                variant_ops.c.variant_id == variant_id, variant_ops.c.asset_id == e.asset_id,
                variant_ops.c.op == kind))).one_or_none()
            if found is not None:
                await session.execute(update(variant_ops).where(variant_ops.c.id == found.id).values(
                    data={**found.data, **data}, base_version=e.version if e.version is not None else found.base_version))
                return found.id
            top += 1
            oid = uuid7()
            await session.execute(insert(variant_ops).values(id=oid, variant_id=variant_id, op=kind, asset_id=e.asset_id,
                                                            base_version=e.version, data=data, sort=top))
            return oid

        for e in body.edits:
            if e.kind == "place":
                if e.type_id is None or e.floor_id is None or e.x is None or e.y is None:
                    raise Problem(422, "invalid", "Для нового объекта нужны тип, этаж и точка",
                                  errors=[{"field": "type_id", "message": "нет"}])
                top += 1
                oid = uuid7()
                await session.execute(insert(variant_ops).values(
                    id=oid, variant_id=variant_id, op="add", sort=top,
                    data={"type_id": str(e.type_id), **_place(e), "angle": e.angle or 0,
                          **({"product_id": str(e.product_id)} if e.product_id else {}),
                          "inventory_no": (e.inventory_no or "").strip() or None, "note": e.note or ""}))
                results.append({"op_id": str(oid)})
            elif e.op_id is not None:                       # an object this variant adds
                o = await mine(e.op_id)
                if e.kind == "remove":
                    await session.execute(delete(variant_ops).where(variant_ops.c.id == o.id))
                    results.append({"op_id": None})
                    continue
                data = {**o.data, **(_place(e) if e.kind == "move" else {})}
                if e.kind == "note":
                    data["note"] = e.note or ""
                if e.inventory_no is not None:
                    data["inventory_no"] = e.inventory_no.strip() or None
                if e.product_id is not None:
                    data["product_id"] = str(e.product_id)
                await session.execute(update(variant_ops).where(variant_ops.c.id == o.id).values(data=data))
                results.append({"op_id": str(o.id)})
            elif e.asset_id is not None:                    # an object of the fact
                if e.kind == "remove":
                    await session.execute(delete(variant_ops).where(
                        variant_ops.c.variant_id == variant_id, variant_ops.c.asset_id == e.asset_id))
                    results.append({"op_id": str(await upsert("remove", e, {}))})
                elif e.kind == "move":
                    results.append({"op_id": str(await upsert("move", e, _place(e)))})
                else:
                    results.append({"op_id": str(await upsert("change", e, {"note": e.note or ""}))})
            else:
                raise Problem(422, "invalid", "Укажите объект: asset_id или op_id",
                              errors=[{"field": "asset_id", "message": "нет"}])
        await session.execute(update(variants).where(variants.c.id == variant_id).values(
            version=variants.c.version + 1, updated_at=func.now()))
    return {"results": results}


# ------------------------------------------------------- view and compare ---
@router.get("/variants/{variant_id}/view", tags=["variants"],
            summary="Объекты здания с наложенным вариантом — для показа на плане и в 3D")
async def view(variant_id: UUID, request: Request, floor_id: UUID | None = None,
               me: Identity = Depends(current_identity)) -> dict:
    v = await _variant(request, me, variant_id)
    objects = await fact(request, v.building_id)
    async with request.app.state.db.begin() as session:
        ops = await _ops(session, variant_id)
    laid = overlay.lay(objects, _rows(ops))
    items = [o for o in laid.values() if floor_id is None or o["floor_id"] == str(floor_id)]
    return {"variant": variant_json(v), "items": items}


async def _side(request: Request, me: Identity, building_id: UUID, side: str) -> tuple[dict[str, dict], str]:
    objects = await fact(request, building_id)
    if side == FACT:
        return overlay.fact_objects(objects), "Факт"
    try:
        vid = UUID(side)
    except ValueError as ex:
        raise Problem(422, "invalid", "Сравнивается факт или вариант", errors=[{"field": "a", "message": side}]) from ex
    v = await _variant(request, me, vid)
    if v.building_id != building_id:
        raise Problem(422, "invalid", "Вариант другого здания", errors=[{"field": "a", "message": side}])
    async with request.app.state.db.begin() as session:
        ops = await _ops(session, vid)
    return overlay.lay(objects, _rows(ops)), v.name


@router.get("/compare", tags=["variants"],
            summary="Сравнить два состояния (факт или вариант): что добавлено, убрано, перемещено, изменено; спецификации")
async def compare(request: Request, building_id: UUID, a: str = Query(FACT), b: str = Query(...),
                  me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, building_id)
    (left, name_a), (right, name_b), kinds, makes = await asyncio.gather(
        _side(request, me, building_id, a), _side(request, me, building_id, b), types(request), products(request))
    return {"a": {"id": a, "name": name_a}, "b": {"id": b, "name": name_b}, **overlay.compare(left, right, kinds, makes)}


@router.get("/variants/{variant_id}/spec", tags=["variants"],
            summary="Спецификация варианта с ценами каталога и разницей с фактом")
async def spec(variant_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    v = await _variant(request, me, variant_id)
    cmp = await compare(request, v.building_id, FACT, str(variant_id), me)
    return {"variant": variant_json(v), "items": cmp["items"], "totals": cmp["totals"]}


# ---------------------------------------------------------------- apply ---
async def _assets(request: Request, method: str, path: str, **kw):
    return await request.app.state.client.request(method, "assets", path, token=_token(request), **kw)


def _why(r) -> str:
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code == 409 and body.get("code") == "version_conflict":
        return "объект изменён после того, как вариант был составлен"
    return body.get("detail") or f"ошибка {r.status_code}"


@router.post("/variants/{variant_id}/apply", tags=["variants"],
             summary="Применить вариант: операции выполняет сервис объектов от имени пользователя")
async def apply(variant_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    """What is done leaves the variant; what is refused (the object changed since, a taken inventory number…) stays
    in it, listed with the reason — to be corrected and applied again. A new object without a number is placed
    on the plan off the books; the number can be given later in its card."""
    v = await _variant(request, me, variant_id)
    if v.status != "draft":
        raise Problem(409, "applied", "Вариант уже применён")
    async with request.app.state.db.begin() as session:
        ops = await _ops(session, variant_id)
    done, refused, versions = [], [], {}
    for o in ops:
        d = o.data or {}
        if o.op == "add":
            r = await _assets(request, "POST", "/assets", json={
                "type_id": d["type_id"], "floor_id": d["floor_id"], "x": d["x"], "y": d["y"], "angle": d.get("angle") or 0,
                "product_id": d.get("product_id"), "inventory_no": d.get("inventory_no"), "note": d.get("note") or ""})
        else:
            version = versions.get(o.asset_id, o.base_version)
            if version is None:
                cur = await _assets(request, "GET", f"/assets/{o.asset_id}")
                version = cur.json().get("version") if cur.status_code == 200 else 0
            if o.op == "move":
                r = await _assets(request, "POST", f"/assets/{o.asset_id}/move",
                                  json={**{k: d[k] for k in overlay.PLACE if k in d}, "version": version})
            elif o.op == "change":
                r = await _assets(request, "PATCH", f"/assets/{o.asset_id}", json={"note": d.get("note") or "", "version": version})
            else:
                r = await _assets(request, "POST", f"/assets/{o.asset_id}/state", json={"state": "retired", "version": version})
        if r.status_code in (200, 201):
            body = r.json()
            if o.asset_id:
                versions[o.asset_id] = body.get("version")
            done.append({"op_id": str(o.id), "op": o.op, "asset_id": body.get("id")})
        else:
            refused.append({"op_id": str(o.id), "op": o.op, "asset_id": str(o.asset_id) if o.asset_id else None,
                            "reason": _why(r)})
    result = {"applied": done, "refused": refused, "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "by": me.sub}
    async with request.app.state.db.begin() as session:
        if done:
            await session.execute(delete(variant_ops).where(variant_ops.c.id.in_([UUID(x["op_id"]) for x in done])))
        v = (await session.execute(update(variants).where(variants.c.id == variant_id).values(
            status="applied" if not refused else "draft", last_result=result, applied_at=func.now() if done else variants.c.applied_at,
            version=variants.c.version + 1, updated_at=func.now()).returning(variants))).one()
        await emit(session, "planning.variant.applied", ("variant", v.id),
                   {"variant_id": str(v.id), "applied": len(done), "refused": len(refused)}, building_id=v.building_id)
        return {**variant_json(v, await _ops(session, variant_id)), "result": result}
