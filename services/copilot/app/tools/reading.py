"""Reading tools: the building, its rooms, objects, catalog, people, rights, journal, variants, reports."""
# ruff: noqa: E501  (descriptions for the model are prose; they are not wrapped)
from __future__ import annotations

from typing import Literal
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from . import Ctx, ToolError, tool

ASSET_FIELDS = ("id", "inventory_no", "type_name", "type_id", "product_name", "state", "serial_no", "note", "floor_id",
                "room_id", "x", "y", "angle", "elevation", "responsible_id", "props", "needs_placement", "needs_fill",
                "container_id", "version")


def _building(ctx: Ctx, given: str | None) -> str:
    b = given or ctx.building_id
    if not b:
        raise ToolError("Не задано здание: укажите building_id (список — buildings)")
    return b


async def _room_names(ctx: Ctx, ids: set[str]) -> dict[str, dict]:
    if not ids:
        return {}
    got = await ctx.call("POST", "buildings", "/rooms/batch-get", json={"ids": sorted(ids)})
    return {r["id"]: r for r in got.get("items", [])}


async def _people_names(ctx: Ctx, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    try:
        got = await ctx.call("POST", "people", "/people/batch-get", json={"ids": sorted(ids)})
    except ToolError:
        return {}
    return {p["id"]: p.get("full_name") or "" for p in got.get("items", [])}


def _room_label(r: dict | None) -> str:
    if not r:
        return ""
    return " ".join(x for x in (r.get("number"), r.get("name")) if x) or r.get("id", "")


# ------------------------------------------------------------------ buildings ---
class NoArgs(BaseModel):
    pass


@tool("buildings", "Здания, доступные пользователю: id, название, адрес, число этажей. Начните с него, если здание не открыто.")
async def buildings(ctx: Ctx, args: NoArgs) -> dict:
    got = await ctx.get("buildings", "/buildings")
    return {"buildings": [{k: b.get(k) for k in ("id", "name", "address", "floors")} for b in got.get("items", [])]}


class BuildingArg(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое у пользователя")


@tool("building_overview", """Здание целиком: этажи с помещениями (id, номер, название, вид, площадь) и сколько в здании
объектов учёта. Координаты и контуры не отдаёт.""")
async def building_overview(ctx: Ctx, args: BuildingArg) -> dict:
    b = _building(ctx, args.building_id)
    tree = await ctx.get("buildings", f"/buildings/{b}/tree")
    floors = []
    for f in tree.get("floors", []):
        rooms = [{"id": r["id"], "number": r.get("number"), "name": r.get("name"), "type": r.get("type"),
                  "area": round(r["area"], 1) if r.get("area") is not None else None}
                 for r in f.get("rooms", []) if r.get("status", "active") == "active"]
        floors.append({"id": f["id"], "name": f.get("name"), "level": f.get("level"), "height": f.get("height"),
                       "rooms": rooms, "area": round(sum(r["area"] or 0 for r in rooms), 1)})
    counts = {}
    try:
        got = await ctx.get("assets", "/assets", building_id=b, limit=1)
        counts["assets"] = got.get("total")
    except ToolError as ex:
        counts["assets"] = str(ex)
    bld = tree.get("building") or {}
    return {"building": {k: bld.get(k) for k in ("id", "name", "address")}, "floors": floors, "counts": counts}


class FindRooms(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    q: str | None = Field(None, description="часть номера или названия помещения, например «214» или «серверная»")
    floor_id: str | None = None
    type: str | None = Field(None, description="вид помещения: office, corridor, wc, stair, lift, technical, meeting, storage…")
    limit: int = Field(50, ge=1, le=500)


@tool("find_rooms", "Поиск помещений здания по номеру, названию, этажу или виду: id, этаж, номер, название, вид, площадь.")
async def find_rooms(ctx: Ctx, args: FindRooms) -> dict:
    b = _building(ctx, args.building_id)
    got = await ctx.get("buildings", "/rooms", building_id=b, floor_id=args.floor_id, q=args.q, type=args.type,
                        limit=args.limit)
    return {"rooms": [{k: r.get(k) for k in ("id", "floor_id", "number", "name", "type", "area")}
                      for r in got.get("items", [])]}


class RoomArg(BaseModel):
    room_id: str = Field(description="id помещения (из find_rooms или контекста экрана)")


@tool("room", "Помещение подробно: данные, объекты учёта в нём (с состоянием, ответственным и свойствами) и люди, привязанные к нему.")
async def room(ctx: Ctx, args: RoomArg) -> dict:
    r = await ctx.get("buildings", f"/rooms/{args.room_id}")
    out = {"room": {k: r.get(k) for k in ("id", "building_id", "floor_id", "number", "name", "type", "area", "status")}}
    try:
        got = await ctx.get("assets", "/assets", room_id=args.room_id, limit=500)
        people = await _people_names(ctx, {a["responsible_id"] for a in got.get("items", []) if a.get("responsible_id")})
        out["assets"] = [_asset_brief(a, people=people) for a in got.get("items", [])]
        out["assets_total"] = got.get("total")
    except ToolError as ex:
        out["assets"] = str(ex)
    try:
        got = await ctx.get("people", f"/rooms/{args.room_id}/people")
        out["people"] = [{k: p.get(k) for k in ("id", "full_name", "position", "department", "workplace_asset_id")}
                         for p in got.get("items", [])]
    except ToolError as ex:
        out["people"] = str(ex)
    return out


# --------------------------------------------------------------------- assets ---
def _asset_brief(a: dict, *, rooms: dict | None = None, people: dict | None = None) -> dict:
    out = {k: a.get(k) for k in ASSET_FIELDS if a.get(k) not in (None, "", False, {}) or k in ("x", "y")}
    if rooms is not None:
        out["room"] = _room_label(rooms.get(a.get("room_id")))
    if people is not None and a.get("responsible_id"):
        out["responsible"] = people.get(a["responsible_id"], "")
    return out


class FindAssets(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    q: str | None = Field(None, description="часть типа, марки, инвентарного или серийного номера")
    floor_id: str | None = None
    room_id: str | None = None
    type_id: str | None = Field(None, description="тип каталога (search_catalog)")
    category_id: str | None = None
    state: str | None = Field(None, description="in_use | faulty | repair | stock | retired | all; по умолчанию — все кроме списанных")
    responsible_id: str | None = Field(None, description="id человека")
    needs_placement: bool | None = Field(None, description="true — требующие размещения (помещение снято)")
    needs_fill: bool | None = Field(None, description="true — с незаполненными обязательными свойствами")
    props: dict[str, str] | None = Field(None, description="""отбор по свойствам: {"warranty_until.lte": "2026-10-31",
"serial": "A12"} — ключ свойства, с суффиксом .gte/.lte для дат и чисел (ключи — в type_schema или в карточке объекта)""")
    limit: int = Field(50, ge=1, le=200)
    cursor: int = Field(0, ge=0, description="смещение для следующей страницы (next из ответа)")


@tool("find_assets", """Объекты учёта по фильтрам: здание, этаж, помещение, тип, состояние, ответственный, свойства, текст.
Отдаёт инвентарный номер, тип, марку, состояние, помещение, ответственного, свойства; total — сколько всего подходит.""")
async def find_assets(ctx: Ctx, args: FindAssets) -> dict:
    b = _building(ctx, args.building_id) if not args.room_id else args.building_id
    params = {"building_id": b, "q": args.q, "floor_id": args.floor_id, "room_id": args.room_id, "type_id": args.type_id,
              "category_id": args.category_id, "state": args.state, "responsible_id": args.responsible_id,
              "needs_placement": args.needs_placement, "needs_fill": args.needs_fill,
              "limit": args.limit, "cursor": args.cursor}
    for k, v in (args.props or {}).items():
        params[f"prop.{k}"] = v
    got = await ctx.get("assets", "/assets", **{k: (str(v).lower() if isinstance(v, bool) else v)
                                                 for k, v in params.items()})
    items = got.get("items", [])
    rooms = await _room_names(ctx, {a["room_id"] for a in items if a.get("room_id")})
    people = await _people_names(ctx, {a["responsible_id"] for a in items if a.get("responsible_id")})
    return {"total": got.get("total"), "next": got.get("next"),
            "assets": [_asset_brief(a, rooms=rooms, people=people) for a in items]}


class AssetArg(BaseModel):
    asset_id: str = Field(description="id объекта")
    history: bool = Field(False, description="добавить историю изменений (последние 30)")


@tool("asset", "Карточка объекта: тип, марка, помещение, состояние, ответственный, свойства со схемой (ключи, названия, кто правит), файлы; по желанию история.")
async def asset(ctx: Ctx, args: AssetArg) -> dict:
    a = await ctx.get("assets", f"/assets/{args.asset_id}")
    rooms = await _room_names(ctx, {a["room_id"]} if a.get("room_id") else set())
    people = await _people_names(ctx, {a["responsible_id"]} if a.get("responsible_id") else set())
    out = _asset_brief(a, rooms=rooms, people=people)
    out["building_id"] = a.get("building_id")
    schema = a.get("schema") or {}
    out["schema"] = [{k: p.get(k) for k in ("key", "title", "kind", "unit", "options", "required", "editable_by")}
                     for p in (schema.get("properties") if isinstance(schema, dict) else schema) or []]
    out["type_props"] = a.get("type_props")
    out["can"] = a.get("can")
    out["children"] = [_asset_brief(c) for c in a.get("children") or []]
    if args.history:
        got = await ctx.get("assets", f"/assets/{args.asset_id}/history")
        out["history"] = [{k: h.get(k) for k in ("at", "actor", "action", "changes", "entry", "id")}
                          for h in (got.get("items") if isinstance(got, dict) else got or [])[:30]]
    return out


# -------------------------------------------------------------------- catalog ---
class SearchCatalog(BaseModel):
    q: str | None = Field(None, description="часть названия типа; без q — только разделы каталога")
    category_id: str | None = None
    with_products: bool = Field(False, description="добавить марки и модели (продукты) с ценами")
    limit: int = Field(30, ge=1, le=200)


@tool("search_catalog", """Каталог: разделы и типы (что это за вещь: «стол 1400×700», «камера купольная») с габаритами,
ценой-оценкой; по желанию марки и модели типа с артикулом, поставщиком и ценой.""")
async def search_catalog(ctx: Ctx, args: SearchCatalog) -> dict:
    cats = await ctx.get("catalog", "/categories")
    out: dict = {"categories": [{k: c.get(k) for k in ("id", "name", "parent_id")} for c in cats.get("items", [])]}
    if args.q or args.category_id:
        got = await ctx.get("catalog", "/types", q=args.q, category_id=args.category_id, active="true")
        types = got.get("items", [])[: args.limit]
        out["types"] = [{k: t.get(k) for k in ("id", "name", "category_id", "size", "elevation", "price", "currency",
                                               "portable", "container", "wall_mounted", "ceiling_mounted", "values")}
                        for t in types]
        if args.with_products:
            for t in out["types"]:
                p = await ctx.get("catalog", "/products", type_id=t["id"], active="true")
                t["products"] = [{k: x.get(k) for k in ("id", "vendor", "name", "article", "supplier", "price", "currency")}
                                 for x in p.get("items", [])]
    return out


class TypeArg(BaseModel):
    type_id: str


@tool("type_schema", "Схема свойств типа каталога: ключи (для отбора в find_assets по props), названия, вид, единицы, кто правит.")
async def type_schema(ctx: Ctx, args: TypeArg) -> dict:
    got = await ctx.get("catalog", f"/types/{args.type_id}/schema")
    props = got.get("properties") if isinstance(got, dict) else got
    return {"type_id": args.type_id, "properties": [
        {k: p.get(k) for k in ("key", "title", "kind", "unit", "options", "required", "stored", "editable_by")}
        for p in props or []]}


# --------------------------------------------------------------------- people ---
class FindPeople(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    q: str | None = Field(None, description="часть имени, должности")
    room_id: str | None = Field(None, description="люди, привязанные к помещению")
    department: str | None = None
    limit: int = Field(50, ge=1, le=500)


@tool("people", "Люди справочника: кто есть, должность, подразделение; привязанные к зданию или помещению.")
async def people(ctx: Ctx, args: FindPeople) -> dict:
    b = args.building_id or ctx.building_id
    got = await ctx.get("people", "/people", q=args.q, building_id=None if args.room_id else b, room_id=args.room_id,
                        department=args.department, limit=args.limit)
    return {"people": [{k: p.get(k) for k in ("id", "full_name", "position", "department", "email", "phone", "status")}
                       for p in got.get("items", [])]}


class PersonArg(BaseModel):
    person_id: str


@tool("person", "Человек подробно: данные, помещения и рабочие места, к которым привязан, объекты под его ответственностью.")
async def person(ctx: Ctx, args: PersonArg) -> dict:
    p = await ctx.get("people", f"/people/{args.person_id}")
    out = {"person": {k: p.get(k) for k in ("id", "full_name", "position", "department", "email", "phone", "status")}}
    try:
        got = await ctx.get("people", f"/people/{args.person_id}/assignments")
        ids = {a["room_id"] for a in got.get("items", []) if a.get("room_id")}
        rooms = await _room_names(ctx, ids)
        out["rooms"] = [{"room_id": a.get("room_id"), "room": _room_label(rooms.get(a.get("room_id"))),
                         "workplace_asset_id": a.get("workplace_asset_id")} for a in got.get("items", [])]
    except ToolError as ex:
        out["rooms"] = str(ex)
    try:
        got = await ctx.get("assets", "/assets", responsible_id=args.person_id, limit=100)
        out["responsible_for"] = [_asset_brief(a) for a in got.get("items", [])]
        out["responsible_total"] = got.get("total")
    except ToolError as ex:
        out["responsible_for"] = str(ex)
    return out


# --------------------------------------------------------------------- rights ---
class GrantsArg(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    person_id: str | None = Field(None, description="права одного человека")


@tool("grants", """Кто что может в здании: назначения «человек — роль (viewer, responsible, admin) — область
(здание, этаж, помещение, объект)» и откуда они (вручную, по привязке к помещению, по ответственности). Администратору здания.""")
async def grants(ctx: Ctx, args: GrantsArg) -> dict:
    b = _building(ctx, args.building_id)
    got = await ctx.get("access", "/grants", building_id=b, person_id=args.person_id)
    items = got.get("items", [])
    people = await _people_names(ctx, {g["person_id"] for g in items if g.get("person_id")})
    return {"grants": [{"id": g.get("id"), "person_id": g.get("person_id"), "person": people.get(g.get("person_id"), ""),
                        "role": g.get("role"), "scope": g.get("scope"), "origin": g.get("origin")} for g in items]}


@tool("my_rights", "Права самого пользователя: администратор ли системы, какие здания видит, какие роли и области назначены.")
async def my_rights(ctx: Ctx, args: NoArgs) -> dict:
    got = await ctx.get("access", "/me/scopes")
    return {"admin": got.get("admin"), "person_id": got.get("person_id"), "buildings": got.get("buildings"),
            "grants": [{k: g.get(k) for k in ("role", "scope", "building_id", "origin")} for g in got.get("grants", [])]}


# -------------------------------------------------------------------- journal ---
class JournalArg(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    room_id: str | None = None
    asset_id: str | None = None
    person_id: str | None = None
    type: str | None = Field(None, description="вид события точно («assets.asset.moved») или по началу («assets.»)")
    from_: str | None = Field(None, alias="from", description="с даты-времени ISO")
    to: str | None = None
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = Field(None, description="next предыдущей страницы")


@tool("journal", "Журнал событий здания, помещения, объекта или человека за период: кто, когда, что сделал. Новые сначала.")
async def journal(ctx: Ctx, args: JournalArg) -> dict:
    b = args.building_id or ctx.building_id
    if not any((b, args.room_id, args.asset_id, args.person_id)):
        raise ToolError("Укажите здание, помещение, объект или человека")
    got = await ctx.get("journal", "/events", building_id=None if (args.room_id or args.asset_id) else b,
                        room_id=args.room_id, asset_id=args.asset_id, person_id=args.person_id, type=args.type,
                        **{"from": args.from_}, to=args.to, limit=args.limit, cursor=args.cursor)
    return {"next": got.get("next"), "events": [
        {"time": e.get("time"), "type": e.get("type"), "actor": e.get("actor"), "subject": e.get("subject"),
         "room_id": e.get("room_id"), "asset_id": e.get("asset_id"), "data": e.get("data")} for e in got.get("items", [])]}


# ------------------------------------------------------------------- planning ---
@tool("variants", "Варианты расстановки здания (проектирование): id, название, от чего сделан, черновик или применён, устарел ли.")
async def variants(ctx: Ctx, args: BuildingArg) -> dict:
    b = _building(ctx, args.building_id)
    got = await ctx.get("planning", "/variants", building_id=b)
    return {"variants": [{k: v.get(k) for k in ("id", "name", "based_on", "status", "stale", "stale_reasons", "version")}
                         for v in got.get("items", [])]}


class CompareArg(BaseModel):
    building_id: str | None = Field(None, description="id здания; по умолчанию — открытое")
    a: str = Field("fact", description="«fact» или id варианта")
    b: str = Field(description="id варианта (или «fact»)")


@tool("compare_variants", "Сравнить факт и вариант или два варианта: что добавлено, убрано, перемещено, изменено; спецификации с ценами и разница.")
async def compare_variants(ctx: Ctx, args: CompareArg) -> dict:
    bld = _building(ctx, args.building_id)
    return await ctx.get("planning", "/compare", building_id=bld, a=args.a, b=args.b)


class VariantArg(BaseModel):
    variant_id: str


@tool("variant", "Вариант подробно: операции (добавить, переместить, изменить, убрать) с конфликтами и спецификация с ценами каталога.")
async def variant(ctx: Ctx, args: VariantArg) -> dict:
    v = await ctx.get("planning", f"/variants/{args.variant_id}")
    out = {k: v.get(k) for k in ("id", "name", "based_on", "status", "stale", "stale_reasons", "counts", "last_result", "version")}
    out["ops"] = [{k: o.get(k) for k in ("id", "op", "asset_id", "data", "conflict")} for o in v.get("ops", [])[:200]]
    try:
        out["spec"] = await ctx.get("planning", f"/variants/{args.variant_id}/spec")
    except ToolError as ex:
        out["spec"] = str(ex)
    return out


# -------------------------------------------------------------------- reports ---
class ReportArg(BaseModel):
    kind: Literal["assets_xlsx", "room_sheet_pdf"] = Field(description="assets_xlsx — список объектов в Excel по фильтрам; room_sheet_pdf — ведомость помещения")
    room_id: str | None = Field(None, description="для ведомости помещения")
    filters: dict[str, str] | None = Field(None, description="для Excel: building_id, floor_id, room_id, type_id, category_id, state, responsible_id, needs_placement, needs_fill, q")


@tool("report_link", "Ссылка на отчёт, который пользователь скачает сам: Excel со списком объектов по фильтрам или ведомость помещения (PDF). Данные строятся по правам скачивающего.")
async def report_link(ctx: Ctx, args: ReportArg) -> dict:
    if args.kind == "room_sheet_pdf":
        if not args.room_id:
            raise ToolError("Для ведомости нужен room_id")
        return {"url": f"/api/reports/rooms/{args.room_id}/sheet.pdf", "title": "Ведомость помещения (PDF)"}
    f = dict(args.filters or {})
    f.setdefault("building_id", ctx.building_id or "")
    f = {k: v for k, v in f.items() if v}
    if not f.get("building_id"):
        raise ToolError("Для Excel нужно здание (building_id)")
    return {"url": "/api/reports/assets.xlsx?" + urlencode(f), "title": "Список объектов (Excel)"}


# ------------------------------------------------------------------------ ui ---
class ShowArg(BaseModel):
    what: Literal["room", "asset", "plan", "variant", "journal", "people", "assets"] = Field(
        description="room — карточка помещения на плане; asset — карточка объекта; plan — план этажа; variant — вариант; journal — журнал здания; people — люди; assets — список объектов")
    id: str | None = Field(None, description="id помещения, объекта, этажа или варианта")
    building_id: str | None = None
    label: str | None = Field(None, description="короткая подпись, что показано")


@tool("show", "Открыть пользователю в интерфейсе: помещение на плане, карточку объекта, план этажа, вариант, журнал, людей. Данных не меняет.")
async def show(ctx: Ctx, args: ShowArg) -> dict:
    b = args.building_id or ctx.building_id
    if args.what == "asset":
        if not args.id:
            raise ToolError("Нужен id объекта")
        if not b:
            a = await ctx.get("assets", f"/assets/{args.id}")
            b = a.get("building_id")
        href = f"#/b/{b}/assets/{args.id}"
    elif args.what == "room":
        if not args.id:
            raise ToolError("Нужен id помещения")
        if not b:
            r = await ctx.get("buildings", f"/rooms/{args.id}")
            b = r.get("building_id")
        href = f"#/b/{b}/plan/{(await ctx.get('buildings', f'/rooms/{args.id}')).get('floor_id')}/{args.id}"
    else:
        if not b:
            raise ToolError("Не задано здание")
        href = {"plan": f"#/b/{b}/plan" + (f"/{args.id}" if args.id else ""),
                "variant": f"#/b/{b}/variants" + (f"/{args.id}" if args.id else ""),
                "journal": f"#/b/{b}/journal", "people": f"#/b/{b}/people",
                "assets": f"#/b/{b}/assets"}[args.what]
    cmd = {"href": href, "label": args.label or ""}
    ctx.events.append({"type": "ui", **cmd})
    return {"shown": cmd}


# ------------------------------------------------------------- room geometry ---
class RoomGeometryArg(BaseModel):
    room_id: str = Field(description="id помещения")


@tool("room_geometry", """Геометрия помещения для расстановки (считает код): габариты и площадь, стены по порядку обхода с длиной
и направлением (к какой стороне света), какие проёмы — двери и окна — на каждой стене и где, что уже стоит и у какой стены.
Зови перед расстановкой, чтобы не ставить экран над дверью и столы не окнами.""")
async def room_geometry(ctx: Ctx, args: RoomGeometryArg) -> dict:
    import math

    r = await ctx.get("buildings", f"/rooms/{args.room_id}")
    from ..geometry import outer_ring
    ring = outer_ring(r.get("polygon"))
    if len(ring) < 3:
        raise ToolError("У помещения нет контура")
    xs, ys = [p[0] for p in ring], [p[1] for p in ring]
    plan = await ctx.get("buildings", f"/floors/{r['floor_id']}/plan")
    plan = plan.get("plan") or {}
    openings = plan.get("openings") or []

    def side_name(dx: float, dy: float) -> str:
        # the outward normal of a counter-clockwise ring's edge: to the right of the direction of walking
        nx, ny = dy, -dx
        if abs(nx) >= abs(ny):
            return "восток (правая)" if nx > 0 else "запад (левая)"
        return "север (верхняя)" if ny > 0 else "юг (нижняя)"

    area2 = sum(ring[i][0] * ring[(i + 1) % len(ring)][1] - ring[(i + 1) % len(ring)][0] * ring[i][1] for i in range(len(ring)))
    if area2 < 0:
        ring = ring[::-1]
    walls = []
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        length = math.dist(a, b)
        if length < 0.3:
            continue
        dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        on_wall = []
        for o in openings:
            c = o.get("center")
            if not c:
                continue
            # distance from the opening's centre to the wall segment
            tt = max(0.0, min(length, (c[0] - a[0]) * dx + (c[1] - a[1]) * dy))
            q = (a[0] + dx * tt, a[1] + dy * tt)
            if math.dist(c, q) <= 0.35:
                on_wall.append({"kind": o.get("kind"), "width": o.get("width"), "at_m_from_start": round(tt, 2), "center": [round(c[0], 2), round(c[1], 2)]})
        walls.append({"n": len(walls) + 1, "from": [round(a[0], 2), round(a[1], 2)], "to": [round(b[0], 2), round(b[1], 2)],
                      "length": round(length, 2), "side": side_name(dx, dy), "openings": on_wall,
                      "free": not on_wall})
    try:
        got = await ctx.get("assets", "/assets", room_id=args.room_id, limit=200)
        items = []
        for a in got.get("items", []):
            if a.get("x") is None:
                continue
            near = min(walls, key=lambda w: _dist_to_segment((a["x"], a["y"]), w["from"], w["to"])) if walls else None
            items.append({"id": a["id"], "type": a.get("type_name"), "inventory_no": a.get("inventory_no"), "x": a["x"], "y": a["y"],
                          "angle": a.get("angle"), "near_wall": near["n"] if near and _dist_to_segment((a["x"], a["y"]), near["from"], near["to"]) < 1.0 else None})
    except ToolError as ex:
        items = str(ex)
    return {"room": {k: r.get(k) for k in ("id", "number", "name", "type", "area", "floor_id")},
            "bbox": [round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)],
            "size": [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)],
            "walls": walls, "objects": items,
            "hint": "координаты — метры плана; угол объекта: 0 — лицом на юг (−y), 90 — на запад, 180 — на север (+y), 270 — на восток; "
                    "предмет у стены стоит спиной к ней"}


def _dist_to_segment(p, a, b) -> float:
    import math
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    ln = (bx - ax) ** 2 + (by - ay) ** 2
    tt = 0.0 if ln < 1e-12 else max(0.0, min(1.0, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / ln))
    return math.dist(p, (ax + (bx - ax) * tt, ay + (by - ay) * tt))
