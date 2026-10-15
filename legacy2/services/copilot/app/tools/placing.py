# ruff: noqa: E501
"""Placing by rules (the planning service counts): items along walls or on a grid, detectors by area, what the
cameras see, what stands wrong. Places become a variant the user looks at and applies."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from . import Ctx, ToolError, tool
from .proposing import Place, ProposeObjects, propose_objects
from .reading import _building


class FloorArg(BaseModel):
    floor_id: str | None = Field(None, description="id этажа; по умолчанию — открытый у пользователя")


def _floor(ctx: Ctx, given: str | None) -> str:
    f = ctx.ui.get("floor")
    fid = given or (f.get("id") if isinstance(f, dict) else None)
    if not fid:
        raise ToolError("Не задан этаж: укажите floor_id (этажи — building_overview)")
    return fid


class PlaceByRules(BaseModel):
    type_id: str = Field(description="тип каталога (search_catalog)")
    floor_id: str | None = Field(None, description="все помещения этажа (кроме коридоров, лестниц, санузлов, технических)")
    room_ids: list[str] | None = Field(None, max_length=100, description="или только эти помещения")
    count: int = Field(1, ge=1, le=200, description="сколько в каждом помещении")
    where: Literal["along_wall", "center", "corners", "grid", "front_of"] = Field("along_wall", description="along_wall — вдоль стен спиной к ним; corners — по углам; grid / center — рядами по помещению; front_of — перед объектом-опорой лицом к нему (кресла к столу)")
    side: Literal["north", "south", "east", "west"] | None = Field(None, description="для along_wall / corners: только стены этой стороны (side из room_geometry)")
    anchor_asset_id: str | None = Field(None, description="для front_of: id объекта в учёте, перед которым ставить")
    anchor: dict | None = Field(None, description="для front_of перед предметом, которого ещё нет в учёте (только предложен): {type_id, x, y, angle}")
    companion_type_id: str | None = Field(None, description="к каждому поставленному предмету — спутник перед ним лицом к нему: кресло к каждому столу, стул к каждому месту за стойкой. Один вызов вместо двух.")
    gap: float = Field(0.2, ge=0, le=5, description="м между предметами")
    summary: str | None = Field(None, max_length=2000)
    then: Literal["return", "propose"] = Field("propose", description="return — только показать места; propose — сразу предложение")


@tool("place_by_rules", """Расставить предметы типа по правилам (считает код): внутри контура, не на других предметах, не в дверях
и проходах, не на перегородках; настенное (экраны, доски) — только на стену и не над проёмами. Рабочие места одним вызовом:
type_id стола, where=along_wall, side стены, companion_type_id кресла — кресло встанет перед каждым столом лицом к нему.
Стол для совещаний — center с companion стульев; шкафы — along_wall или corners; экран — на стену без проёмов напротив столов.
front_of ставит перед объектом учёта (anchor_asset_id) или перед только предложенным (anchor {type_id, x, y, angle}).
Стену выбирай по room_geometry и передавай side. Точное место на стене или в точке — place_at.
Результат — предложение (или только места при then=return).""", kind="propose")
async def place_by_rules(ctx: Ctx, args: PlaceByRules) -> dict:
    b = _building(ctx, None)
    if args.where == "front_of" and not (args.anchor_asset_id or args.anchor):
        raise ToolError("front_of: укажите anchor_asset_id (объект учёта) или anchor {type_id, x, y, angle} (предложенный предмет)")
    got = await ctx.call("POST", "planning", "/placements", json={
        "building_id": b, "type_id": args.type_id, "floor_id": args.floor_id, "room_ids": args.room_ids,
        "count": args.count, "where": args.where, "gap": args.gap, "anchor_asset_id": args.anchor_asset_id,
        "anchor": args.anchor, "companion_type_id": args.companion_type_id, "side": args.side})
    places = got.get("places", [])
    out = {"item": got.get("item"), "rooms": got.get("rooms"), "placed": len(places)}
    if args.then == "return" or not places:
        if not places:
            out["note"] = "Ни одного места не нашлось: помещения заняты или не подходят"
        out["places"] = places[:200]
        return out
    item = got.get("item") or {}
    mate = got.get("companion") or {}
    what = item.get("name", "") + (f" с {mate['name']}" if mate else "")
    v = await propose_objects(ctx, ProposeObjects(
        summary=args.summary or f"Поставить {len(places)} предметов: {what} ({args.where}) в {len(got.get('rooms', []))} помещениях",
        places=[Place(type_id=p.get("type_id") or args.type_id, floor_id=p["floor_id"], x=p["x"], y=p["y"], angle=p.get("angle")) for p in places]), checked=True)
    return {**out, **v}


class Wall(BaseModel):
    side: Literal["north", "south", "east", "west"] = Field(description="сторона стены (side из room_geometry)")
    along: float | Literal["start", "middle", "end"] = Field("middle", description="метры от угла до края предмета, или start / middle / end")
    origin: Literal["start", "end"] = Field("start", description="от какого угла считать along: start — точка from стены в room_geometry, end — точка to")


class Point(BaseModel):
    x: float
    y: float
    angle: float = Field(0, description="0 — лицом на юг (−y), 90 — на запад, 180 — на север (+y), 270 — на восток")


class PlaceAt(BaseModel):
    type_id: str = Field(description="тип каталога")
    room_id: str
    wall: Wall | None = Field(None, description="к стене: спиной к ней, в заданном месте вдоль неё")
    point: Point | None = Field(None, description="или в точку с заданным углом")
    count: int = Field(1, ge=1, le=20, description="для wall: сколько в ряд от указанного места")
    companion_type_id: str | None = Field(None, description="спутник перед каждым поставленным лицом к нему (кресло к столу)")
    gap: float = Field(0.2, ge=0, le=5)
    summary: str | None = Field(None, max_length=2000)
    then: Literal["return", "propose"] = Field("propose", description="return — только места; propose — сразу предложение")


@tool("place_at", """Поставить предмет точно: к названной стене (wall: side; along — метры от угла до края предмета или
start/middle/end; origin — от какого угла: start = точка from стены в room_geometry, end = точка to), спиной к ней, или в
точку (point: x, y, angle). Не пересчитывай метры сам — назови угол через origin. Код проверяет место: внутри контура, не в дверях,
не на перегородке, не на других предметах, настенное — не над проёмом. Если место занято — сдвигает к ближайшему
свободному и говорит, на сколько и почему (notes); если свободного нет — places пусто и причина в notes.
Результат — предложение (или только места при then=return).""", kind="propose")
async def place_at(ctx: Ctx, args: PlaceAt) -> dict:
    b = _building(ctx, None)
    if bool(args.wall) == bool(args.point):
        raise ToolError("Укажите одно: wall {side, along} или point {x, y, angle}")
    body = {"building_id": b, "type_id": args.type_id, "room_ids": [args.room_id], "count": args.count if args.wall else 1,
            "gap": args.gap, "companion_type_id": args.companion_type_id}
    if args.wall:
        body |= {"where": "at_wall", "side": args.wall.side, "along": args.wall.along, "from_end": args.wall.origin == "end"}
    else:
        body |= {"where": "at_point", "anchor": {"x": args.point.x, "y": args.point.y, "angle": args.point.angle}}
    got = await ctx.call("POST", "planning", "/placements", json=body)
    places = got.get("places", [])
    notes = [n for r in got.get("rooms", []) for n in r.get("notes", [])]
    out = {"item": got.get("item"), "placed": len(places), "notes": notes}
    if args.then == "return" or not places:
        if not places:
            out["note"] = "Не поставлено: " + ("; ".join(notes) or "помещение не найдено или точка вне его")
        out["places"] = places
        return out
    item = got.get("item") or {}
    mate = got.get("companion") or {}
    what = item.get("name", "") + (f" с {mate['name']}" if mate else "")
    where = f"к стене {args.wall.side}" if args.wall else f"в точку ({args.point.x}, {args.point.y})"
    v = await propose_objects(ctx, ProposeObjects(
        summary=args.summary or f"Поставить {what} {where}" + (f" ({'; '.join(notes)})" if notes else ""),
        places=[Place(type_id=p.get("type_id") or args.type_id, floor_id=p["floor_id"], x=p["x"], y=p["y"], angle=p.get("angle")) for p in places]), checked=True)
    return {**out, **v}


class LayoutPlace(BaseModel):
    type_id: str
    x: float
    y: float
    angle: float = 0
    room_id: str | None = Field(None, description="в каком помещении предмет должен оказаться")


class LayoutMove(BaseModel):
    asset_id: str
    x: float
    y: float
    angle: float | None = None


class CheckLayout(BaseModel):
    floor_id: str | None = Field(None, description="этаж; по умолчанию — открытый у пользователя")
    places: list[LayoutPlace] = Field(default_factory=list, max_length=200, description="задуманные новые предметы")
    moves: list[LayoutMove] = Field(default_factory=list, max_length=200, description="задуманные перестановки")


@tool("check_layout", """Проверить задуманную расстановку до предложения (считает код): для каждого предмета — в каком
помещении окажется, что не так (вне помещений, в дверях или проходе, на перегородке, на другом предмете, настенное не на
стене или над проёмом), у какой стены и спиной ли к ней, на что смотрит (faces), и ближайшее свободное место (fix),
если задуманное не годится. Ничего не ставит. Зови, когда координаты придумал сам, прежде чем propose_objects.""")
async def check_layout(ctx: Ctx, args: CheckLayout) -> dict:
    b = _building(ctx, None)
    if not args.places and not args.moves:
        raise ToolError("Нечего проверять: укажите places или moves")
    return await ctx.call("POST", "planning", "/layout-check", json={
        "building_id": b, "floor_id": _floor(ctx, args.floor_id),
        "places": [p.model_dump() for p in args.places], "moves": [m.model_dump() for m in args.moves]})


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
        places=[Place(type_id=type_id, floor_id=p["floor_id"], x=p["x"], y=p["y"], angle=0) for p in places]), checked=True)
    return {**out, **v}


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
