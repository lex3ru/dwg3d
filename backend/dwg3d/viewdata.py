"""Layer objects (furniture, cameras, lines, zones...) and pins (markers,
comments) on the floors of a drawing: one row per object.

Clients refer to floors by the candidate id of the build they show (c0,
c3...) and send the `version` of the row they changed; a row changed or
deleted by someone else in the meantime is a conflict (HTTP 409) and nothing
of the request is written. Objects of a locked layer cannot be changed.
Every change is recorded in audit_log.
"""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth, events, layers, shapes
from .models import AuditLog, CatalogItem, Drawing, Floor, Layer, LayerObject, Pin, Project
from .rooms import Locator

MAX_PINS = 500
MAX_OBJECTS = 5000          # per drawing
MAX_POINTS = 5000           # vertices of one line / polygon
MAX_OPS = 5000
GEOMS = ("point", "polyline", "polygon", "route")
# props shown as top-level fields of an object (CCTV camera: view angle, range)
FLAT_PROPS = {"fov": (1, 360), "range": (0.5, 300)}
PIN_KINDS = {"markers": "marker", "comments": "comment"}


class Invalid(ValueError):
    """Bad input (HTTP 400)."""


class Conflict(Exception):
    """Rows changed by someone else (HTTP 409): [{id, current | None}]."""

    def __init__(self, message: str, conflicts: list[dict]):
        super().__init__(message)
        self.conflicts = conflicts


# ------------------------------------------------------------ validation ---
def num(v, lo, hi, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise Invalid(f"view.{name}: ожидается число в [{lo}, {hi}]")
    return float(v)


def string(v, name, n=2000):
    if not isinstance(v, str) or len(v) > n:
        raise Invalid(f"view.{name}: ожидается строка до {n} символов")
    return v


def pin_item(it, name: str) -> dict:
    if not isinstance(it, dict) or not isinstance(it.get("pos"), list) or len(it["pos"]) != 3:
        raise Invalid(f"view.{name}: элемент {{id, pos: [x, y, z], text}}")
    return {"id": string(it.get("id") or uuid.uuid4().hex[:8], f"{name}.id", 40),
            "floor": string(it.get("floor") or "", f"{name}.floor", 40),
            "pos": [num(c, -1e5, 1e5, f"{name}.pos") for c in it["pos"]],
            "text": string(it.get("text", ""), f"{name}.text"),
            "label": string(it.get("label", ""), f"{name}.label", 8),
            "author": string(it.get("author", ""), f"{name}.author", 80),
            "created": num(it.get("created") or time.time(), 0, 1e11, f"{name}.created")}


def _xy(v, name) -> list[float]:
    if not isinstance(v, list) or len(v) != 2:
        raise Invalid(f"{name}: ожидается [x, y]")
    return [num(c, -1e5, 1e5, name) for c in v]


def object_item(it) -> dict:
    """A layer object: geometry (a point of a catalog item — position,
    turn in degrees counter-clockwise, optional size override [w, d, h] and
    mounting height; or a polyline / polygon — its vertices), the layer, the
    floor, and kind-specific props (for CCTV cameras the view angle `fov`,
    deg, and `range`, m, also given as top-level fields)."""
    if not isinstance(it, dict):
        raise Invalid("объект: {id, layer, floor, item, at: [x, y], angle} или {geom, points}")
    geom = it.get("geom") or "point"
    if geom not in GEOMS:
        raise Invalid(f"geom: {', '.join(GEOMS)}")
    f = {"id": string(it.get("id") or uuid.uuid4().hex[:8], "object.id", 40),
         "floor": string(it.get("floor") or "", "object.floor", 40), "geom": geom,
         "angle": num(it.get("angle", 0), -3600, 3600, "object.angle") % 360}
    if it.get("layer") is not None:
        f["layer"] = string(it["layer"], "object.layer", 40)
    if geom == "point":
        if not isinstance(it.get("item"), str):
            raise Invalid("объект: элемент {id, floor, item, at: [x, y], angle}")
        f["item"] = string(it["item"], "object.item", 80)
        f["at"] = _xy(it.get("at"), "object.at")
    elif geom == "route":
        # stops and the way are in props (shapes.py); the object stands where the route starts
        stops = (it.get("props") or {}).get("stops") if isinstance(it.get("props"), dict) else None
        if not isinstance(stops, list) or not stops or not isinstance(stops[0], dict):
            raise Invalid("маршрут: props.stops — список остановок {floor, at: [x, y]}")
        f["at"] = _xy(stops[0].get("at"), "stops[0].at")
        f["floor"] = string(stops[0].get("floor") or "", "stops[0].floor", 40)
    else:
        pts = it.get("points")
        least = 3 if geom == "polygon" else 2
        if not isinstance(pts, list) or not least <= len(pts) <= MAX_POINTS:
            raise Invalid(f"object.points: от {least} до {MAX_POINTS} точек [x, y]")
        f["points"] = [_xy(p, "object.points") for p in pts]
        f["at"] = _xy(it["at"], "object.at") if it.get("at") is not None else list(f["points"][0])
        if it.get("item") is not None:
            f["item"] = string(it["item"], "object.item", 80)
    if it.get("size") is not None:
        if not isinstance(it["size"], list) or len(it["size"]) != 3:
            raise Invalid("object.size: ожидается [ширина, глубина, высота]")
        f["size"] = [num(c, 0.01, 50, "object.size") for c in it["size"]]
    if it.get("note"):
        f["note"] = string(it["note"], "object.note", 500)
    if it.get("elev") is not None:                  # mounting height override
        f["elev"] = num(it["elev"], 0, 20, "object.elev")
    props = it.get("props") or {}
    if not isinstance(props, dict) or len(repr(props)) > (600000 if geom == "route" else 20000):
        raise Invalid("object.props: объект")
    props = {k: v for k, v in props.items() if k not in FLAT_PROPS}
    for k, (lo, hi) in FLAT_PROPS.items():
        if it.get(k) is not None:
            props[k] = num(it[k], lo, hi, f"object.{k}")
    f["props"] = props
    return f


# ------------------------------------------------------------------ JSON ---
def _floors(s: Session, did: str) -> dict[int, Floor]:
    return {f.id: f for f in s.scalars(select(Floor).where(Floor.drawing_id == did))}


def _cand(floors: dict[int, Floor], fid: int | None) -> str:
    f = floors.get(fid) if fid is not None else None
    return (f.candidate or "") if f else ""


def object_json(r: LayerObject, floors: dict[int, Floor]) -> dict:
    o = {"id": r.id, "layer": r.layer_id, "floor": _cand(floors, r.floor_id), "room": r.room_id, "geom": r.geom,
         "at": [r.x, r.y], "angle": r.angle}
    if r.item_id is not None:
        o["item"] = r.item_id
    if r.points is not None:
        o["points"] = r.points
    for k in ("size", "note", "elev"):
        if (v := getattr(r, k)) is not None:
            o[k] = list(v) if k == "size" else v
    props = dict(r.props or {})
    if r.geom == "route":
        props = shapes.route_props_json(props, lambda fid: _cand(floors, fid))
    for k in FLAT_PROPS:
        if k in props:
            o[k] = props.pop(k)
    if props:
        o["props"] = props
    o["version"] = r.version
    if not o["floor"]:                              # its sheet is gone (or it never had a floor)
        f = floors.get(r.floor_id) if r.floor_id is not None else None
        o["_anchor"] = {"name": f.name} if f else None
    return o


def pin_json(r: Pin, floors: dict[int, Floor]) -> dict:
    return {"id": r.id, "floor": _cand(floors, r.floor_id), "pos": [r.x, r.y, r.z], "text": r.text,
            "label": r.label, "author": r.author, "created": r.created_at.timestamp(), "version": r.version}


def view_data(s: Session, did: str, layer_ids: set[str] | None = None) -> dict:
    """Objects and pins of a drawing: furniture (catalog items on a floor),
    furniture_unplaced (their floor is gone), shapes (lines, polygons, routes),
    markers, comments — only non-empty lists; objects of `layer_ids` only when given."""
    floors = _floors(s, did)
    out: dict[str, list] = {"furniture": [], "furniture_unplaced": [], "shapes": [], "markers": [], "comments": []}
    q = select(LayerObject).where(LayerObject.drawing_id == did).order_by(LayerObject.created_at, LayerObject.id)
    if layer_ids is not None:
        q = q.where(LayerObject.layer_id.in_(layer_ids))
    for r in s.scalars(q):
        o = object_json(r, floors)
        if r.geom != "point":
            out["shapes"].append(o)
        else:
            out["furniture" if o["floor"] else "furniture_unplaced"].append(o)
    for r in s.scalars(select(Pin).where(Pin.drawing_id == did).order_by(Pin.created_at, Pin.id)):
        out[r.kind + "s"].append(pin_json(r, floors))
    return {k: v for k, v in out.items() if v}


def _strip(o: dict | None) -> dict | None:
    """A row's JSON as input for the next change (without derived fields)."""
    return None if o is None else {k: v for k, v in o.items() if k not in ("version", "_anchor", "room")}


# ---------------------------------------------------------------- writes ---
# why the current changes are made, added to the audit log's actor (e.g. applying an agent's proposal)
audit_via: ContextVar[str | None] = ContextVar("dwg3d_audit_via", default=None)

def _me_id() -> int | None:
    me = auth.current.get()
    return me.id if me else None


def audit_entry(s, pid, entity, eid, action, before, after, drawing_id=None):
    """Record a change by the user of the current request, and tell the open
    windows of the project once it commits (events.py)."""
    me = auth.current.get()
    actor = me.actor() if me else None
    if (via := audit_via.get()) is not None:
        actor = f"{actor} · {via}" if actor else via
    s.add(AuditLog(project_id=pid, drawing_id=drawing_id, entity=entity, entity_id=eid, action=action,
                   user_id=me.id if me else None, actor=actor,
                   before=_strip(before), after=_strip(after)))
    if pid:
        events.publish(s, pid, {"drawing": drawing_id, "entity": entity, "id": eid, "action": action},
                       {"user_id": me.id if me else None, "actor": actor,
                        "agent": me.agent["name"] or me.agent["id"] if me and me.agent else None})


def layer_kind(layer: Layer) -> str:
    return layer.kind


def lock_drawing(s: Session, did: str, build: int | None) -> Drawing:
    """Share-lock the drawing (a finishing build takes it exclusively and moves
    the rows); refuse requests made against another build's floor ids."""
    d = s.scalar(select(Drawing).where(Drawing.id == did, Drawing.deleted_at.is_(None))
                 .with_for_update(read=True))
    if d is None:
        raise LookupError(did)
    if build is not None and build != d.current_build:
        raise Conflict("Модель была перестроена: обновите страницу, чтобы не потерять изменения", [])
    return d


def apply(s: Session, did: str, entity: str, ops: list, build: int | None = None) -> dict:
    """Create / update / delete layer objects (entity 'object') or pins ('pin')
    on a drawing.

    ops: [{"op": "create" | "update" | "delete", "id", "version", ...fields}]
    Updates and deletes must carry the version they were made against. All
    or nothing. Returns {"items": [changed rows as JSON], "deleted": [ids]}.
    """
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise Invalid(f"ops: ожидается список до {MAX_OPS} операций")
    d = lock_drawing(s, did, build)
    pid = d.project_id
    floors = _floors(s, did)
    by_cand = {f.candidate: f.id for f in floors.values() if f.candidate}
    ids = [o.get("id") for o in ops if isinstance(o, dict) and isinstance(o.get("id"), str)]
    if entity == "object":
        Model, to_json, limit = LayerObject, object_json, MAX_OBJECTS
        rows = {r.id: r for r in s.scalars(select(LayerObject).where(LayerObject.project_id == pid,
                                                                     LayerObject.id.in_(ids)).with_for_update())}
        count = s.scalar(select(func.count()).select_from(LayerObject).where(LayerObject.drawing_id == did))
        project_layers = {x.id: x for x in s.scalars(select(Layer).where(Layer.project_id == pid))}
        loc = Locator(s)
    else:
        Model, to_json, limit = Pin, pin_json, MAX_PINS * 2
        rows = {r.id: r for r in s.scalars(select(Pin).where(Pin.drawing_id == did, Pin.id.in_(ids)).with_for_update())}
        count = s.scalar(select(func.count()).select_from(Pin).where(Pin.drawing_id == did))
    conflicts, changed, deleted = [], {}, []

    def floor_id(cand: str, allow_none: bool):
        if not cand and allow_none:
            return None
        if cand not in by_cand:
            raise Invalid(f"этаж «{cand}» не найден в текущей сборке")
        return by_cand[cand]

    def unlocked(layer: Layer):
        if layer.locked:
            raise Invalid(f"слой «{layer.name}» заблокирован")
        return layer

    for o in ops:
        if not isinstance(o, dict) or o.get("op") not in ("create", "update", "delete"):
            raise Invalid("ops: элемент {op: create | update | delete, id, version, ...}")
        op, row = o["op"], rows.get(o.get("id"))
        fields = {k: v for k, v in o.items() if k not in ("op", "version")}
        if op != "create" and not isinstance(o.get("id"), str):
            raise Invalid(f"ops: для {op} нужен id")
        if row is not None and entity == "object" and row.drawing_id != did:
            if op == "create":
                raise Invalid(f"объект «{row.id}» уже есть на другом чертеже проекта")
            raise Invalid(f"объект «{row.id}» — на другом чертеже проекта")
        if op == "create" and row is not None:
            conflicts.append({"id": row.id, "current": to_json(row, floors)})
            continue
        if op != "create" and row is not None and o.get("version") != row.version:
            conflicts.append({"id": row.id, "current": to_json(row, floors)})
            continue
        if op == "delete":
            if row is not None:
                if entity == "object":
                    unlocked(project_layers[row.layer_id])
                audit_entry(s, pid, entity, row.id, "delete", to_json(row, floors), None, did)
                s.delete(row)
                rows.pop(row.id)
                deleted.append(row.id)
                count -= 1
            continue
        if op == "update" and row is None:
            conflicts.append({"id": o["id"], "current": None})
            continue
        before = to_json(row, floors) if row is not None else None
        if entity == "object":
            base = _strip(before) or {}
            if "geom" in fields and row is not None and fields["geom"] != row.geom:
                raise Invalid("тип геометрии объекта не меняется")
            v = object_item({**base, **fields})
            fid = floor_id(v["floor"], False) if (row is None or "floor" in fields) else row.floor_id
            item = v.get("item")
            cat = None
            if item is not None:
                ci = s.get(CatalogItem, item)
                if ci is None and (row is None or item != row.item_id):
                    raise Invalid(f"предмета «{item}» нет в каталоге")
                cat = ci.category_id if ci else None
            if row is not None:
                unlocked(project_layers[row.layer_id])
            if "layer" in fields or row is None:
                if v.get("layer"):
                    layer = project_layers.get(v["layer"])
                    if layer is None:
                        raise Invalid(f"слоя «{v['layer']}» нет в проекте")
                else:
                    try:
                        layer = layers.default_layer(s, pid, item, v["geom"])
                    except layers.LayerError as ex:
                        raise Invalid(str(ex)) from ex
                    project_layers[layer.id] = layer
                if (why := layers.accepts(unlocked(layer), v["geom"], cat)) is not None:
                    raise Invalid(why)
                layer_id = layer.id
            else:
                layer_id = row.layer_id
            props = v["props"]
            try:
                if v["geom"] == "route":
                    props = shapes.route_props(props, lambda c: floor_id(c, False))
                elif v["geom"] == "polygon" and layer_kind(project_layers[layer_id]) == "zones":
                    props = shapes.zone_props(props)
                elif v["geom"] == "polyline" and layer_kind(project_layers[layer_id]) == "network":
                    props = shapes.cable_props(props)
            except shapes.ShapeError as ex:
                raise Invalid(str(ex)) from ex
            x, y = v["at"]
            if row is not None and fid == row.floor_id and x == row.x and y == row.y:
                room = row.room_id
            else:
                room = loc.room(fid, x, y)
            vals = {"layer_id": layer_id, "floor_id": fid, "room_id": room, "item_id": item, "geom": v["geom"],
                    "x": x, "y": y, "angle": v["angle"], "points": v.get("points"), "size": v.get("size"),
                    "note": v.get("note"), "elev": v.get("elev"), "props": props}
            new_row = dict(project_id=pid, drawing_id=did)
        else:
            kind = (row.kind + "s") if row is not None else o.get("kind")
            if kind in PIN_KINDS.values():
                kind += "s"
            if kind not in PIN_KINDS:
                raise Invalid("pins: kind — marker или comment")
            if row is None and not fields.get("author") and (me := auth.current.get()) and me.id:
                fields["author"] = me.name
            v = pin_item({**(_strip(before) or {}), **fields}, kind)
            fid = floor_id(v["floor"], True) if (row is None or "floor" in fields) else row.floor_id
            vals = {"kind": PIN_KINDS[kind], "floor_id": fid, "x": v["pos"][0], "y": v["pos"][1], "z": v["pos"][2],
                    "text": v["text"], "label": v["label"], "author": v["author"]}
            if row is None:
                vals["created_at"] = datetime.fromtimestamp(v["created"], tz=timezone.utc)
            new_row = dict(drawing_id=did)
        if row is None:
            if count >= limit:
                raise Invalid(f"не больше {limit} объектов на чертеже")
            row = Model(**new_row, id=v["id"], version=1, updated_by=_me_id(), **vals)
            s.add(row)
            rows[row.id] = row
            count += 1
        else:
            if all(getattr(row, k) == (list(x) if isinstance(x, tuple) else x) for k, x in vals.items()):
                changed[row.id] = row                    # nothing new: no version bump, no audit entry
                continue
            for k, x in vals.items():
                setattr(row, k, x)
            row.updated_by = _me_id()
            row.version += 1
            row.updated_at = func.now()
        s.flush()
        after = to_json(row, floors)
        audit_entry(s, pid, entity, row.id, "create" if before is None else "update", before, after, did)
        changed[row.id] = row
    if conflicts:
        raise Conflict("Изменено другим пользователем: обновите данные и повторите", conflicts)
    if changed or deleted:
        s.execute(Drawing.__table__.update().where(Drawing.id == did).values(updated_at=func.now()))
        s.execute(Project.__table__.update().where(Project.id == pid).values(updated_at=func.now()))
    s.flush()
    return {"items": [to_json(r, floors) for r in changed.values()], "deleted": deleted}


def audit(s: Session, pid: str, limit: int = 100, drawing_id: str | None = None) -> list[dict]:
    """Changes in a project (or in one of its drawings), newest first."""
    q = select(AuditLog).where(AuditLog.project_id == pid)
    if drawing_id is not None:
        q = q.where(AuditLog.drawing_id == drawing_id)
    q = q.order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 1000))
    return [{"id": a.id, "at": a.at.timestamp(), "drawing_id": a.drawing_id, "entity": a.entity,
             "entity_id": a.entity_id, "action": a.action,
             "user_id": a.user_id, "actor": a.actor, "before": a.before, "after": a.after} for a in s.scalars(q)]
