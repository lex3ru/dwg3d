# ruff: noqa: E501
"""Placing by rules (the planning service counts): items along walls or on a grid, detectors by area, what the
cameras see, what stands wrong. Places become a variant the user looks at and applies."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from . import Ctx, ToolError, tool
from .proposing import Place, ProposeObjects, propose_objects
from .reading import _building


class PlaceByRules(BaseModel):
    type_id: str = Field(description="тип каталога (search_catalog)")
    floor_id: str | None = Field(None, description="все помещения этажа (кроме коридоров, лестниц, санузлов, технических)")
    room_ids: list[str] | None = Field(None, max_length=100, description="или только эти помещения")
    count: int = Field(1, ge=1, le=200, description="сколько в каждом помещении")
    where: Literal["along_wall", "center", "corners", "grid", "front_of"] = Field("along_wall", description="along_wall — вдоль стен спиной к ним; corners — по углам; grid / center — рядами по помещению; front_of — перед объектом-опорой лицом к нему (кресла к столу)")
    anchor_asset_id: str | None = Field(None, description="для front_of: id объекта, перед которым ставить (например, стола)")
    gap: float = Field(0.2, ge=0, le=5, description="м между предметами")
    summary: str | None = Field(None, max_length=2000)
    then: Literal["return", "propose"] = Field("propose", description="return — только показать места; propose — сразу предложение")


@tool("place_by_rules", """Расставить предметы типа по правилам (считает код): внутри контура, не на других предметах, не в дверях
и проходах, не на перегородках; настенное (экраны, доски) — только на стену и не над проёмами. Как обставлять кабинет:
столы — along_wall (лучше у окна, спиной к стене); кресла к столу — where=front_of с anchor_asset_id стола (по одному
вызову на стол); шкафы — along_wall или corners; стол для совещаний — center, стулья к нему — front_of; экран — на стену
напротив столов. Сначала узнай room_geometry. Результат — предложение (или только места при then=return).""", kind="propose")
async def place_by_rules(ctx: Ctx, args: PlaceByRules) -> dict:
    b = _building(ctx, None)
    if args.where == "front_of" and not args.anchor_asset_id:
        raise ToolError("front_of: укажите anchor_asset_id — объект, перед которым ставить")
    got = await ctx.call("POST", "planning", "/placements", json={
        "building_id": b, "type_id": args.type_id, "floor_id": args.floor_id, "room_ids": args.room_ids,
        "count": args.count, "where": args.where, "gap": args.gap, "anchor_asset_id": args.anchor_asset_id})
    places = got.get("places", [])
    out = {"item": got.get("item"), "rooms": got.get("rooms"), "placed": len(places)}
    if args.then == "return" or not places:
        if not places:
            out["note"] = "Ни одного места не нашлось: помещения заняты или не подходят"
        out["places"] = places[:200]
        return out
    item = got.get("item") or {}
    v = await propose_objects(ctx, ProposeObjects(
        summary=args.summary or f"Поставить {len(places)} × {item.get('name', '')} ({args.where}) в {len(got.get('rooms', []))} помещениях",
        places=[Place(type_id=args.type_id, floor_id=p["floor_id"], x=p["x"], y=p["y"], angle=p.get("angle")) for p in places]))
    return {**out, **v}


class PlaceDetectors(BaseModel):
    type_id: str | None = Field(None, description="тип извещателя; пусто — первый тип каталога с радиусом контроля")
    floor_id: str | None = None
    room_ids: list[str] | None = Field(None, max_length=100)
    then: Literal["return", "propose"] = "propose"


@tool("place_detectors", """Пожарные извещатели по площади (считает код): сколько есть в каждом помещении, сколько нужно
(каждый защищает ≈0,7·π·r² пола, не меньше одного на помещение), где добавить — равномерно, подальше от имеющихся.
Результат — предложение с местами (или только расчёт при then=return).""", kind="propose")
async def place_detectors(ctx: Ctx, args: PlaceDetectors) -> dict:
    b = _building(ctx, None)
    type_id = args.type_id
    if not type_id:
        types = await ctx.get("catalog", "/types", active="true")
        found = next((t for t in types.get("items", []) if (t.get("values") or {}).get("detect_radius")), None)
        if found is None:
            raise ToolError("В каталоге нет типа с радиусом контроля (detect_radius): укажите type_id извещателя")
        type_id = found["id"]
    got = await ctx.call("POST", "planning", "/detectors", json={"building_id": b, "type_id": type_id, "floor_id": args.floor_id, "room_ids": args.room_ids})
    places = got.get("places", [])
    out = {"item": got.get("item"), "rule": got.get("rule"), "rooms": got.get("rooms"), "to_add": len(places)}
    if args.then == "return" or not places:
        if not places:
            out["note"] = "Извещателей хватает: добавлять нечего"
        return out
    item = got.get("item") or {}
    v = await propose_objects(ctx, ProposeObjects(
        summary=f"Добавить {len(places)} × {item.get('name', 'извещатель')} по площади в {sum(1 for r in got.get('rooms', []) if r.get('add'))} помещениях",
        places=[Place(type_id=type_id, floor_id=p["floor_id"], x=p["x"], y=p["y"], angle=0) for p in places]))
    return {**out, **v}


class FloorArg(BaseModel):
    floor_id: str | None = Field(None, description="id этажа; по умолчанию — открытый у пользователя")


def _floor(ctx: Ctx, given: str | None) -> str:
    f = ctx.ui.get("floor")
    fid = given or (f.get("id") if isinstance(f, dict) else None)
    if not fid:
        raise ToolError("Не задан этаж: укажите floor_id (этажи — building_overview)")
    return fid


@tool("coverage", "Что видят камеры этажа (считает код): доля площади каждого помещения в обзоре, где различимо лицо, крупнейшие слепые места.")
async def coverage(ctx: Ctx, args: FloorArg) -> dict:
    b = _building(ctx, None)
    return await ctx.get("planning", "/coverage", building_id=b, floor_id=_floor(ctx, args.floor_id))


@tool("check_placement", """Что стоит не так на этаже (считает код): предметы в дверях и проходах, на перегородках и колоннах,
друг на друге, вне стен; пустые помещения, которые должны быть обставлены; плохо просматриваемые камерами; двери уже 80 см.
По найденному предлагай исправления (move_to_room, propose_variant, place_by_rules).""")
async def check_placement(ctx: Ctx, args: FloorArg) -> dict:
    b = _building(ctx, None)
    return await ctx.get("planning", "/checks", building_id=b, floor_id=_floor(ctx, args.floor_id), limit=50)
