"""MCP server for AI agents (Streamable HTTP at /api/mcp).

Reading tools for every token; proposals (proposals.py: changes a person
applies or rejects) for tokens of the "propose" and "write" modes; writing
tools (objects through viewdata.apply, creating and changing layers) for
tokens of the "write" mode only. Proposing and writing are limited in size
and rate (MAX_OPS operations a call, WRITES_PER_MINUTE calls).

The agent connects with its token (tokens.py) in `Authorization: Bearer`.
Every tool call resolves the token again and runs as its user, through the
same functions and access checks as the HTTP API (the MCP session runs in
its own task, so the request's auth.current does not reach the tools).

Answers are compact for a language model: plan coordinates in metres rounded
to centimetres, floors by id (c0, c1... — what objects refer to) with their
names, rooms by id with names and areas, catalog items with their names.

  claude mcp add --transport http dwg3d https://<site>/api/mcp \\
      --header "Authorization: Bearer dwg3d_..."
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from shapely.geometry import box
from sqlalchemy import func, select

from . import access, auth, db, layers, planning, proposals, reports, rooms, store, tokens, viewdata
from .models import CatalogCategory, CatalogItem, Drawing, Floor, Layer, LayerObject, Project, Proposal, Room

PATH = "/api/mcp"
MAX_OBJECTS = 500
MAX_OPS = 200                   # operations in one apply_changes
WRITES_PER_MINUTE = 30          # writing calls of one token (per API process)

INSTRUCTIONS = """\
Проект из программы «Поэтажные планы → 3D»: DWG-чертежи зданий (корпуса), их этажи
и помещения, слои проектных данных (мебель и оборудование, видеонаблюдение, пожарная
сигнализация, СКУД, Wi-Fi, СКС, маршруты людей, зоны) и объекты на слоях.
Начните с project_overview. Координаты — метры в плане этажа; этаж задаётся id
(c0, c1…) внутри чертежа; помещения — числовые id из list_rooms. Позиции каталога
(id вида doc.couch) ищутся search_catalog. С токеном «предложения» или «изменение»
(token_mode в project_overview) можно предложить изменения объектов —
propose_changes: человек увидит их на плане и примет или отклонит (proposal_status).
Это предпочтительный путь для заметных правок. Чтобы не считать координаты самому:
place_in_room (расставить в помещении у стен / в центре / по углам / сеткой),
place_row (ряд), camera_coverage (что видят камеры) — у расстановки then="propose"
сразу создаёт предложение. Изменять напрямую можно только с
токеном «изменение»: apply_changes, create_layer, update_layer. Изменения сохраняются сразу (люди увидят их, обновив страницу) и пишутся
в журнал под вашим токеном —
перед массовыми правками опишите пользователю, что собираетесь сделать."""

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
CHANGE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

mcp = MCPServer("dwg3d", title="Поэтажные планы → 3D", instructions=INSTRUCTIONS)


# ------------------------------------------------------------------ access ---
_writes: dict[str, deque] = defaultdict(deque)
_writes_lock = threading.Lock()


def _rate(token_id: str):
    """At most WRITES_PER_MINUTE writing calls of a token a minute (in this process)."""
    now = time.monotonic()
    with _writes_lock:
        q = _writes[token_id]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= WRITES_PER_MINUTE:
            raise ToolError(f"Слишком часто: не больше {WRITES_PER_MINUTE} изменений в минуту — "
                            "объединяйте операции в один apply_changes")
        q.append(now)


@contextmanager
def _agent(ctx: Context, write: bool = False, propose: bool = False):
    """The token's agent as the current user of this call, and its project id.
    `write`: a change — the token must be of the write mode, access checks
    take an editor (as for a POST of the HTTP API); `propose`: a proposal — a
    token of the propose or write mode, reading access. Errors of the data
    become tool errors, the transaction rolled back."""
    h = (ctx.headers or {}).get("authorization", "")
    me = tokens.resolve(h[7:].strip()) if h[:7].lower() == "bearer " else None
    if me is None or me.agent is None:
        raise ToolError("Нужен действующий токен агента (Authorization: Bearer dwg3d_…)")
    if write:
        if me.agent["mode"] != "write":
            raise ToolError(f"Токен в режиме «{tokens.MODE_NAMES[me.agent['mode']]}»: изменять нельзя. "
                            "Нужен токен в режиме «изменение» (проект → «ИИ-агенты»)")
        _rate(me.agent["id"])
    elif propose:
        if me.agent["mode"] not in ("propose", "write"):
            raise ToolError("Токен «только чтение»: предлагать изменения нельзя. "
                            "Нужен токен в режиме «предложения» или «изменение» (проект → «ИИ-агенты»)")
        _rate(me.agent["id"])
    t_user, t_method = auth.current.set(me), auth.method.set("POST" if write else "GET")
    try:
        yield me, me.agent["project_id"]
    except access.Denied as ex:
        raise ToolError(str(ex)) from ex
    except (viewdata.Invalid, layers.LayerError, planning.PlanError) as ex:
        raise ToolError(f"Ничего не изменено: {ex}") from ex
    except viewdata.Conflict as ex:
        raise ToolError(f"Ничего не изменено: {ex}. Текущее состояние: "
                        + json.dumps(ex.conflicts, ensure_ascii=False, default=str)[:4000]) from ex
    finally:
        auth.current.reset(t_user)
        auth.method.reset(t_method)


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 2)


def _xy(p) -> list[float]:
    return [round(p[0], 2), round(p[1], 2)]


def _drawing(s, pid: str, did: str) -> Drawing:
    d = store.get_drawing(s, did)
    if d is None or d.project_id != pid:
        raise ToolError(f"Чертёж {did!r} не найден в проекте: см. project_overview")
    access.check_drawing(s, d)
    return d


def _floor(s, did: str, fid: str) -> Floor:
    f = s.scalar(select(Floor).where(Floor.drawing_id == did, Floor.candidate == fid))
    if f is None:
        raise ToolError(f"Этаж {fid!r} не найден в чертеже {did}: см. project_overview")
    return f


def _shown_layers(s, me, pid: str) -> dict[str, Layer]:
    shown = access.visible_layers(me)
    return {x.id: x for x in s.scalars(select(Layer).where(Layer.project_id == pid))
            if shown is None or x.id in shown}


# ------------------------------------------------------------------- tools ---
@mcp.tool(annotations=READ)
def project_overview(ctx: Context) -> dict[str, Any]:
    """Проект целиком: название, ваша роль и режим токена, чертежи с этажами
    (id этажа, название, уровень, отметка и высота, число помещений) и слои
    (id, тип, название, видимость, блокировка, число объектов). Начинайте с него."""
    with _agent(ctx) as (me, pid), db.session() as s:
        p = s.get(Project, pid)
        access.check(s, pid)
        drawings = []
        for d in store.list_drawings(s, pid, me):
            nrooms = dict(s.execute(select(Room.floor_id, func.count()).where(Room.drawing_id == d["id"], Room.idx.is_not(None))
                                    .group_by(Room.floor_id)).all())
            floors = [{"id": f.candidate, "name": f.name or "", "level": f.level, "elevation": _r(f.elevation),
                       "height": _r(f.height), "rooms": nrooms.get(f.id, 0)}
                      for f in s.scalars(select(Floor).where(Floor.drawing_id == d["id"], Floor.candidate.is_not(None))
                                         .order_by(Floor.level, Floor.id))]
            drawings.append({"id": d["id"], "name": d["name"], "status": d["status"], "build": d["build"],
                             "floors": floors})
        shown = access.visible_layers(me)
        lays = [{"id": x["id"], "kind": x["kind"], "kind_name": layers.KINDS.get(x["kind"], {}).get("name", x["kind"]),
                 "name": x["name"], "visible": x["visible"], "locked": x["locked"], "objects": x["count"]}
                for x in layers.list_layers(s, pid) if shown is None or x["id"] in shown]
        return {"project": {"id": p.id, "name": p.name, "description": p.description},
                "my_role": access.project_role(s, me, pid), "token_mode": me.agent["mode"],
                "drawings": drawings, "layers": lays}


@mcp.tool(annotations=READ)
def list_rooms(ctx: Context,
               drawing: Annotated[str, Field(description="id чертежа")],
               floor: Annotated[str | None, Field(description="id этажа (c0, c1…); все этажи, если не задан")] = None,
               query: Annotated[str | None, Field(description="часть названия или типа помещения")] = None,
               outline: Annotated[bool, Field(description="добавить контур помещения (кольца точек [x, y])")] = False) -> dict[str, Any]:
    """Помещения чертежа: id, этаж, название, тип, площадь (м²), центр и габарит
    [xmin, ymin, xmax, ymax] в координатах плана (м)."""
    with _agent(ctx) as (me, pid), db.session() as s:
        d = _drawing(s, pid, drawing)
        q = (select(Room, Floor).join(Floor, Floor.id == Room.floor_id)
             .where(Room.drawing_id == d.id, Room.idx.is_not(None), Floor.candidate.is_not(None))
             .order_by(Floor.level, Room.floor_id, Room.idx))
        if floor is not None:
            q = q.where(Room.floor_id == _floor(s, d.id, floor).id)
        out = []
        needle = (query or "").strip().lower()
        for r, f in s.execute(q):
            if needle and needle not in (r.name or "").lower() and needle not in (r.type or "").lower():
                continue
            o = {"id": r.id, "floor": f.candidate, "floor_name": f.name or "", "name": r.name or "",
                 "type": r.type, "area": _r(r.area)}
            if (poly := rooms.polygon(r.poly)) is not None:
                c = poly.representative_point()
                o["center"], o["bbox"] = _xy((c.x, c.y)), [round(v, 2) for v in poly.bounds]
            if outline:
                o["outline"] = [[_xy(p) for p in ring] for ring in r.poly]
            out.append(o)
        return {"drawing": d.id, "rooms": out}


@mcp.tool(annotations=READ)
def layer_kinds(ctx: Context) -> dict[str, Any]:
    """Типы слоёв: какие виды геометрии (point — позиция каталога, polyline,
    polygon, route) и какие категории каталога в них допустимы; правила
    функциональных слоёв (потоки маршрутов, виды зон, кабели)."""
    with _agent(ctx):
        return layers.kinds_with_rules()


@mcp.tool(annotations=READ)
def search_catalog(ctx: Context,
                   query: Annotated[str | None, Field(description="часть названия, id, артикула или тегов")] = None,
                   category: Annotated[str | None, Field(description="id категории (security, fire, network…)")] = None,
                   limit: Annotated[int, Field(ge=1, le=200)] = 30) -> dict[str, Any]:
    """Каталог мебели и оборудования: категории и найденные позиции (id, название,
    категория, габариты w×d×h, м; цена; для камер — угол и дальность, для
    датчиков — радиус). Без запроса — только список категорий и их размер."""
    with _agent(ctx), db.session() as s:
        counts = dict(s.execute(select(CatalogItem.category_id, func.count()).where(CatalogItem.active)
                                .group_by(CatalogItem.category_id)).all())
        cats = [{"id": c.id, "name": c.name, "items": counts.get(c.id, 0)}
                for c in s.scalars(select(CatalogCategory).order_by(CatalogCategory.sort, CatalogCategory.id))]
        if not query and not category:
            return {"categories": cats}
        q = select(CatalogItem).where(CatalogItem.active).order_by(CatalogItem.sort, CatalogItem.id)
        if category:
            q = q.where(CatalogItem.category_id == category)
        if query:
            like = f"%{query.strip().lower()}%"
            q = q.where(func.lower(CatalogItem.name).like(like) | func.lower(CatalogItem.id).like(like)
                        | func.lower(func.coalesce(CatalogItem.tags, "")).like(like)
                        | func.lower(func.coalesce(CatalogItem.article, "")).like(like))
        items = []
        for i in s.scalars(q.limit(limit)):
            o = {"id": i.id, "name": i.name, "category": i.category_id, "size": [i.w, i.d, i.h]}
            if i.wall:
                o["wall"] = True
            if i.price is not None:
                o["price"] = f"{i.price} {i.currency}"
            if i.camera:
                o["camera"] = i.camera
            if i.params:
                o["params"] = i.params
            items.append(o)
        return {"categories": cats, "items": items}


def _object(o: dict, d: Drawing, lay: dict[str, Layer], rnames: dict[int, str], inames: dict[str, str],
            full: bool) -> dict:
    """A layer object for the agent: names next to ids, coordinates rounded."""
    x = {"id": o["id"], "layer": o["layer"], "layer_name": lay[o["layer"]].name if o["layer"] in lay else None,
         "drawing": d.id, "floor": o["floor"] or None, "geom": o["geom"], "at": _xy(o["at"])}
    if o.get("room") is not None:
        x["room"], x["room_name"] = o["room"], rnames.get(o["room"], "")
    if "item" in o:
        x["item"], x["item_name"] = o["item"], inames.get(o["item"], "")
    if o["geom"] == "point":
        x["angle"] = round(o["angle"], 1)
    if "points" in o:
        x["points"] = [_xy(p) for p in o["points"]] if full or len(o["points"]) <= 8 else len(o["points"])
    for k in ("size", "elev", "note", "fov", "range"):
        if k in o:
            x[k] = o[k]
    props = dict(o.get("props") or {})
    if not full:
        props.pop("path", None)                     # a route's computed way: long, see get_object
        props.pop("origin", None)
    if props:
        x["props"] = props
    if full:
        x["version"] = o["version"]
    return x


def _names(s, objs: list[dict]) -> tuple[dict[int, str], dict[str, str]]:
    rids = {o["room"] for o in objs if o.get("room") is not None}
    iids = {o["item"] for o in objs if "item" in o}
    rnames = dict(s.execute(select(Room.id, Room.name).where(Room.id.in_(rids))).all()) if rids else {}
    inames = dict(s.execute(select(CatalogItem.id, CatalogItem.name).where(CatalogItem.id.in_(iids))).all()) if iids else {}
    return rnames, inames


@mcp.tool(annotations=READ)
def query_objects(ctx: Context,
                  drawing: Annotated[str | None, Field(description="id чертежа; все чертежи проекта, если не задан")] = None,
                  layer: Annotated[str | None, Field(description="id слоя")] = None,
                  floor: Annotated[str | None, Field(description="id этажа (c0…), вместе с drawing")] = None,
                  room: Annotated[int | None, Field(description="id помещения")] = None,
                  item: Annotated[str | None, Field(description="id позиции каталога или её начало (doc., security.cam…)")] = None,
                  bbox: Annotated[list[float] | None, Field(description="[xmin, ymin, xmax, ymax], м — объекты, задевающие прямоугольник", min_length=4, max_length=4)] = None,
                  limit: Annotated[int, Field(ge=1, le=MAX_OBJECTS)] = 200) -> dict[str, Any]:
    """Объекты слоёв по фильтрам: id, слой, чертёж, этаж, помещение, позиция каталога
    (с названием), точка привязки at [x, y] (м), поворот (°); у линий и полигонов —
    вершины (у длинных — их число, полностью — get_object)."""
    with _agent(ctx) as (me, pid), db.session() as s:
        if floor is not None and drawing is None:
            raise ToolError("floor задаётся вместе с drawing")
        lay = _shown_layers(s, me, pid)
        if layer is not None and layer not in lay:
            raise ToolError(f"Слой {layer!r} не найден: см. project_overview")
        ds = [_drawing(s, pid, drawing)] if drawing else [
            d for x in store.list_drawings(s, pid, me) if (d := store.get_drawing(s, x["id"])) is not None]
        fid = _floor(s, ds[0].id, floor).id if floor is not None else None
        area = box(*bbox) if bbox else None
        found, total = [], 0
        for d in ds:
            floors = viewdata._floors(s, d.id)
            q = select(LayerObject).where(LayerObject.drawing_id == d.id, LayerObject.layer_id.in_(list(lay)))
            q = q.where(LayerObject.layer_id == layer) if layer else q
            q = q.where(LayerObject.floor_id == fid) if fid is not None else q
            q = q.where(LayerObject.room_id == room) if room is not None else q
            q = q.where(LayerObject.item_id.startswith(item, autoescape=True)) if item else q
            for r in s.scalars(q.order_by(LayerObject.created_at, LayerObject.id)):
                o = viewdata.object_json(r, floors)
                if area is not None and not area.intersects(_shape(o)):
                    continue
                total += 1
                if len(found) < limit:
                    found.append((o, d))
        rnames, inames = _names(s, [o for o, _ in found])
        return {"total": total, "truncated": total > len(found),
                "objects": [_object(o, d, lay, rnames, inames, False) for o, d in found]}


def _shape(o: dict):
    from shapely.geometry import LineString, Point, Polygon
    pts = o.get("points")
    if o["geom"] == "polygon" and pts:
        return Polygon(pts)
    if o["geom"] == "polyline" and pts:
        return LineString(pts)
    return Point(o["at"])


@mcp.tool(annotations=READ)
def get_object(ctx: Context, id: Annotated[str, Field(description="id объекта")]) -> dict[str, Any]:
    """Объект целиком: все поля и props (у маршрута — остановки и рассчитанный путь),
    версия строки (понадобится для изменений)."""
    with _agent(ctx) as (me, pid), db.session() as s:
        lay = _shown_layers(s, me, pid)
        r = s.scalar(select(LayerObject).where(LayerObject.project_id == pid, LayerObject.id == id,
                                               LayerObject.layer_id.in_(list(lay))))
        if r is None:
            raise ToolError(f"Объект {id!r} не найден")
        d = _drawing(s, pid, r.drawing_id)
        o = viewdata.object_json(r, viewdata._floors(s, d.id))
        rnames, inames = _names(s, [o])
        return _object(o, d, lay, rnames, inames, True)


@mcp.tool(annotations=READ)
def report(ctx: Context,
           kind: Annotated[Literal["equipment", "by_room", "checks"],
                           Field(description="equipment — спецификация по этажам; by_room — по помещениям; "
                                             "checks — проверки (помещения, где не хватает пожарных извещателей)")],
           layer: Annotated[str | None, Field(description="id слоя: только его объекты (для equipment и by_room)")] = None) -> dict[str, Any]:
    """Отчёты проекта, те же, что в программе: спецификация оборудования и проверки."""
    with _agent(ctx) as (me, pid), db.session() as s:
        access.check(s, pid)
        if layer is not None and layer not in _shown_layers(s, me, pid):
            raise ToolError(f"Слой {layer!r} не найден: см. project_overview")
        if kind == "checks":
            return {"fire": reports.fire_check(s, pid, me)}
        shown = access.visible_layers(me)
        return (reports.by_room(s, pid, layer, me, shown) if kind == "by_room"
                else reports.equipment(s, pid, layer, me, shown))


@mcp.tool(annotations=READ)
def recent_changes(ctx: Context,
                   limit: Annotated[int, Field(ge=1, le=200)] = 30,
                   drawing: Annotated[str | None, Field(description="только изменения в этом чертеже")] = None) -> dict[str, Any]:
    """Последние изменения в проекте (журнал): когда, кто (у агента — с названием
    токена), что (объект, слой, чертёж…) и действие; поля до и после."""
    with _agent(ctx) as (_, pid), db.session() as s:
        access.check(s, pid)
        return {"changes": [{k: a[k] for k in ("at", "actor", "entity", "entity_id", "action", "drawing_id", "before", "after")}
                            for a in viewdata.audit(s, pid, limit, drawing)]}


# ------------------------------------------------------------------ writes ---
OPS_HELP = """\
Операции (все или ни одной):
- создать точку каталога: {"op": "create", "layer", "floor", "item", "at": [x, y], "angle"?,
  "size"?: [w, d, h], "elev"?, "note"?, "fov"?, "range"?, "id"?} — id создаётся сам, если не задан;
- линию или полигон: {"op": "create", "geom": "polyline" | "polygon", "layer", "floor",
  "points": [[x, y], …], "props"?} (зоны: props.name, props.zone; кабели: props.cable);
- маршрут: {"op": "create", "geom": "route", "layer", "props": {"stops": [{"floor", "at": [x, y]}, …],
  "flow"?, "name"?}} — путь между остановками пересчитает редактор;
- изменить: {"op": "update", "id", "version", …только меняемые поля};
- удалить: {"op": "delete", "id", "version"}.
version — из query_objects / get_object (у созданных этим вызовом — в ответе)."""


def _changed(res: dict, ops: list[dict], d: Drawing, s, me, pid: str) -> dict[str, Any]:
    created = {o.get("id") for o in ops if o.get("op") == "create"}
    lay = _shown_layers(s, me, pid)
    rnames, inames = _names(s, res["items"])
    objs = [_object(o, d, lay, rnames, inames, False) | {"version": o["version"]} for o in res["items"]]
    return {"created": [o["id"] for o in objs if o["id"] in created],
            "updated": [o["id"] for o in objs if o["id"] not in created],
            "deleted": res["deleted"], "objects": objs}


@mcp.tool(annotations=CHANGE, description=f"""Изменить объекты слоёв на чертеже одним пакетом: создать,
изменить, удалить. Только с токеном «изменение». Не больше {MAX_OPS} операций за вызов.
Объекты заблокированных слоёв не меняются. Если строку уже изменил кто-то другой
(version не совпадает) — ничего не записывается, в ошибке текущее состояние.

{OPS_HELP}""")
def apply_changes(ctx: Context,
                  drawing: Annotated[str, Field(description="id чертежа")],
                  ops: Annotated[list[dict[str, Any]], Field(description="операции, см. описание инструмента",
                                                             min_length=1, max_length=MAX_OPS)],
                  build: Annotated[int | None, Field(description="номер сборки чертежа из project_overview: "
                                                                 "если модель с тех пор перестроили — отказ")] = None) -> dict[str, Any]:
    with _agent(ctx, write=True) as (me, pid), db.session() as s:
        d = _drawing(s, pid, drawing)
        if any(not isinstance(o, dict) for o in ops):
            raise ToolError("ops: список объектов-операций")
        # the agent may leave out ids of new objects: give them here, to tell them in the answer
        ops = [{**o, "id": o.get("id") or uuid.uuid4().hex[:8]} if o.get("op") == "create" else o for o in ops]
        res = viewdata.apply(s, d.id, "object", ops, build=build)
        return _changed(res, ops, d, s, me, pid)


@mcp.tool(annotations=WRITE)
def create_layer(ctx: Context,
                 kind: Annotated[str, Field(description="тип слоя из layer_kinds (furniture, cctv, fire, routes, zones…)")],
                 name: Annotated[str | None, Field(description="название; по умолчанию — название типа", max_length=120)] = None) -> dict[str, Any]:
    """Создать слой проекта (например, вариант расстановки). Только с токеном «изменение»."""
    with _agent(ctx, write=True) as (_, pid), db.session() as s:
        store.get_project(s, pid, lock=True)
        access.check(s, pid)
        layer = layers.create(s, pid, {"kind": kind, "name": name})
        viewdata.audit_entry(s, pid, "layer", layer.id, "create", None, layers.layer_json(layer))
        store.touch_project(s, pid)
        return layers.layer_json(layer, 0)


@mcp.tool(annotations=WRITE)
def update_layer(ctx: Context,
                 id: Annotated[str, Field(description="id слоя")],
                 name: Annotated[str | None, Field(description="новое название", max_length=120)] = None,
                 visible: Annotated[bool | None, Field(description="показывать ли слой")] = None) -> dict[str, Any]:
    """Переименовать слой или включить / выключить его видимость. Блокировку слоя
    меняет только человек; удалить слой агент не может. Только с токеном «изменение»."""
    with _agent(ctx, write=True) as (me, pid), db.session() as s:
        access.check(s, pid)
        layer = s.scalar(select(Layer).where(Layer.id == id, Layer.project_id == pid).with_for_update())
        if layer is None or id not in _shown_layers(s, me, pid):
            raise ToolError(f"Слой {id!r} не найден: см. project_overview")
        v = {k: x for k, x in (("name", name), ("visible", visible)) if x is not None}
        changes = layers.update(layer, v)
        if changes:
            viewdata.audit_entry(s, pid, "layer", id, "update", {k: b for k, (b, _) in changes.items()},
                                 {k: a for k, (_, a) in changes.items()})
            store.touch_project(s, pid)
        return layers.layer_json(layer)



# --------------------------------------------------------------- proposals ---
@mcp.tool(annotations=WRITE, description=f"""Предложить изменения объектов на чертеже: человек увидит их
на плане (новые, изменённые, удаляемые) и применит или отклонит. Ничего не меняется,
пока он не решит. Токен «предложения» или «изменение». Операции проверяются сразу
(как в apply_changes) — с ошибкой предложение не создаётся. До {proposals.MAX_OPS} операций.
summary — для человека: что и зачем, кратко.

{OPS_HELP}""")
def propose_changes(ctx: Context,
                    drawing: Annotated[str, Field(description="id чертежа")],
                    summary: Annotated[str, Field(description="что и зачем меняется — увидит человек", min_length=1, max_length=2000)],
                    ops: Annotated[list[dict[str, Any]], Field(description="операции, как в apply_changes",
                                                               min_length=1, max_length=proposals.MAX_OPS)],
                    build: Annotated[int | None, Field(description="номер сборки из project_overview")] = None) -> dict[str, Any]:
    with _agent(ctx, propose=True) as (_, pid), db.session() as s:
        d = _drawing(s, pid, drawing)
        p = proposals.create(s, d, summary, ops, build)
        viewdata.audit_entry(s, pid, "proposal", p.id, "create", None,
                             {"summary": p.summary, "counts": proposals.counts(p.ops)}, d.id)
        return {**proposals.proposal_json(p, drawing=d),
                "next": "Предложение ждёт решения человека; узнать его — proposal_status"}


@mcp.tool(annotations=READ)
def proposal_status(ctx: Context,
                    id: Annotated[str | None, Field(description="id предложения; без него — последние предложения этого токена")] = None) -> dict[str, Any]:
    """Решение по предложению: ждёт решения, применено, отклонено (с причиной, если
    человек её указал) или устарело (объекты или модель изменились — предложите заново)."""
    with _agent(ctx) as (me, pid), db.session() as s:
        access.check(s, pid)
        if id is None:
            return {"proposals": proposals.listing(s, pid, token=me.agent["id"], limit=20)}
        p = s.scalar(select(Proposal).where(Proposal.id == id, Proposal.project_id == pid))
        if p is None:
            raise ToolError(f"Предложение {id!r} не найдено")
        return proposals.proposal_json(p, proposals._users(s, [p]), s.get(Drawing, p.drawing_id))


# ---------------------------------------------------------- planning tools ---
Then = Literal["return", "propose", "apply"]
THEN_HELP = ("return — только вернуть операции (передать их в propose_changes / apply_changes); "
             "propose — сразу создать предложение (нужен summary); apply — сразу применить (токен «изменение»)")


def _then(ctx: Context, then: str):
    return _agent(ctx, write=then == "apply", propose=then == "propose")


def _finish(s, pid: str, d: Drawing, plan: dict, ops: list[dict], then: str, summary: str | None) -> dict[str, Any]:
    out = {**plan, "ops": ops}
    if not ops or then == "return":
        return out
    if then == "propose":
        if not summary:
            raise ToolError("then=propose: нужен summary — что и зачем, для человека")
        p = proposals.create(s, d, summary, ops, None)
        viewdata.audit_entry(s, pid, "proposal", p.id, "create", None,
                             {"summary": p.summary, "counts": proposals.counts(p.ops)}, d.id)
        return {**out, "proposal": proposals.proposal_json(p, drawing=d)}
    res = viewdata.apply(s, d.id, "object", ops)
    return {**out, "created": [r["id"] for r in res["items"]]}


def _creates(plan: dict, item: str, layer: str | None) -> list[dict]:
    return [{"op": "create", "id": uuid.uuid4().hex[:8], "floor": plan["floor"], "item": item,
             "at": p["at"], "angle": p["angle"], **({"layer": layer} if layer else {})} for p in plan["places"]]


@mcp.tool(annotations=WRITE)
def place_in_room(ctx: Context,
                  drawing: Annotated[str, Field(description="id чертежа")],
                  room: Annotated[int, Field(description="id помещения из list_rooms")],
                  item: Annotated[str, Field(description="id позиции каталога")],
                  count: Annotated[int, Field(ge=1, le=planning.MAX_ITEMS)] = 1,
                  where: Annotated[Literal["along_wall", "center", "corners", "grid"],
                                   Field(description="along_wall — спиной к стенам вдоль них; center — ближе к центру; "
                                                     "corners — в углы; grid — рядами по всему помещению")] = "along_wall",
                  gap: Annotated[float, Field(ge=0, le=5, description="зазор между предметами, м")] = 0.2,
                  layer: Annotated[str | None, Field(description="id слоя; по умолчанию — подходящий для позиции")] = None,
                  then: Annotated[Then, Field(description=THEN_HELP)] = "return",
                  summary: Annotated[str | None, Field(description="для then=propose: что и зачем", max_length=2000)] = None) -> dict[str, Any]:
    """Найти места для предметов каталога в помещении: внутри контура, не на других
    предметах, с зоной обслуживания перед предметом внутри помещения и свободной.
    Возвращает места (at, angle), операции создания и замечания (если поместилось меньше)."""
    with _then(ctx, then) as (_, pid), db.session() as s:
        d = _drawing(s, pid, drawing)
        plan = planning.place_in_room(s, d.id, room, item, count, where, gap)
        return _finish(s, pid, d, plan, _creates(plan, item, layer), then, summary)


@mcp.tool(annotations=WRITE)
def place_row(ctx: Context,
              drawing: Annotated[str, Field(description="id чертежа")],
              floor: Annotated[str, Field(description="id этажа (c0…)")],
              item: Annotated[str, Field(description="id позиции каталога")],
              start: Annotated[list[float], Field(description="[x, y] первого предмета, м", min_length=2, max_length=2)],
              end: Annotated[list[float], Field(description="[x, y] последнего предмета, м", min_length=2, max_length=2)],
              count: Annotated[int | None, Field(ge=1, le=planning.MAX_ITEMS, description="сколько предметов")] = None,
              step: Annotated[float | None, Field(gt=0, le=100, description="или шаг между центрами, м")] = None,
              angle: Annotated[float | None, Field(description="поворот, °; по умолчанию ширина — вдоль ряда")] = None,
              layer: Annotated[str | None, Field(description="id слоя")] = None,
              then: Annotated[Then, Field(description=THEN_HELP)] = "return",
              summary: Annotated[str | None, Field(description="для then=propose: что и зачем", max_length=2000)] = None) -> dict[str, Any]:
    """Ряд одинаковых предметов от start до end (кресла в ожидании, светильники, датчики).
    Пересечения с другими предметами и выход за помещение — в замечаниях, не отказ."""
    with _then(ctx, then) as (_, pid), db.session() as s:
        d = _drawing(s, pid, drawing)
        plan = planning.place_row(s, d.id, _floor(s, d.id, floor), item, start, end, count, step, angle)
        return _finish(s, pid, d, plan, _creates(plan, item, layer), then, summary)


@mcp.tool(annotations=READ)
def camera_coverage(ctx: Context,
                    drawing: Annotated[str, Field(description="id чертежа")],
                    floor: Annotated[str, Field(description="id этажа (c0…)")],
                    room: Annotated[int | None, Field(description="только это помещение")] = None,
                    layer: Annotated[str | None, Field(description="только камеры этого слоя (вариант)")] = None) -> dict[str, Any]:
    """Что видят камеры: по каждому помещению этажа — доля площади в поле зрения камер,
    стоящих в нём, и доля, где различимо лицо; самые большие невидимые участки (габариты).
    Приближённо: обзор ограничен стенами помещения, мебель и перегородки не учитываются."""
    with _agent(ctx) as (me, pid), db.session() as s:
        d = _drawing(s, pid, drawing)
        lay = _shown_layers(s, me, pid)
        if layer is not None and layer not in lay:
            raise ToolError(f"Слой {layer!r} не найден: см. project_overview")
        return planning.camera_coverage(s, _floor(s, d.id, floor), room, {layer} if layer else set(lay))

# --------------------------------------------------------------- HTTP app ---
@asynccontextmanager
async def running():
    """For the API's lifespan: a fresh session manager (each runs only once),
    stateless (any API process answers any request), plain JSON answers.
    DNS-rebinding protection is off: requests carry a token, not cookies."""
    mcp.streamable_http_app(streamable_http_path=PATH, stateless_http=True, json_response=True,
                            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    async with mcp.session_manager.run():
        yield


class Endpoint:
    """The ASGI app of PATH (a class, so that Starlette's Route passes it the raw ASGI call)."""

    async def __call__(self, scope, receive, send):
        await mcp.session_manager.handle_request(scope, receive, send)
