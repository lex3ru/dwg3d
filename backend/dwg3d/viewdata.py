"""Placed furniture and pins (markers, comments): one row per object.

Clients refer to floors by the candidate id of the build they show (c0,
c3...) and send the `version` of the row they changed; a row changed or
deleted by someone else in the meantime is a conflict (HTTP 409) and nothing
of the request is written. Every change is recorded in audit_log.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth
from .models import AuditLog, CatalogItem, Drawing, Floor, Pin, Placement, Project

MAX_PINS = 500
MAX_FURNITURE = 5000
MAX_OPS = 5000
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


def pins(items, name: str) -> list[dict]:
    if not isinstance(items, list) or len(items) > MAX_PINS:
        raise Invalid(f"view.{name}: ожидается список до {MAX_PINS} элементов")
    return [pin_item(it, name) for it in items]


def furniture_item(it) -> dict:
    """Placed furniture / equipment: catalog item id, plan position (m), turn
    (degrees, counter-clockwise), optional size override [w, d, h] (m),
    mounting height; for CCTV cameras the view angle (deg) and range (m)."""
    if (not isinstance(it, dict) or not isinstance(it.get("at"), list) or len(it["at"]) != 2
            or not isinstance(it.get("item"), str)):
        raise Invalid("view.furniture: элемент {id, floor, item, at: [x, y], angle}")
    f = {"id": string(it.get("id") or uuid.uuid4().hex[:8], "furniture.id", 40),
         "floor": string(it.get("floor") or "", "furniture.floor", 40),
         "item": string(it["item"], "furniture.item", 80),
         "at": [num(c, -1e5, 1e5, "furniture.at") for c in it["at"]],
         "angle": num(it.get("angle", 0), -3600, 3600, "furniture.angle") % 360}
    if it.get("size") is not None:
        if not isinstance(it["size"], list) or len(it["size"]) != 3:
            raise Invalid("view.furniture.size: ожидается [ширина, глубина, высота]")
        f["size"] = [num(c, 0.01, 50, "furniture.size") for c in it["size"]]
    if it.get("note"):
        f["note"] = string(it["note"], "furniture.note", 500)
    if it.get("elev") is not None:                  # mounting height override
        f["elev"] = num(it["elev"], 0, 20, "furniture.elev")
    if it.get("fov") is not None:                   # CCTV camera: view angle, range
        f["fov"] = num(it["fov"], 1, 360, "furniture.fov")
    if it.get("range") is not None:
        f["range"] = num(it["range"], 0.5, 300, "furniture.range")
    return f


def furniture(items) -> list[dict]:
    if not isinstance(items, list) or len(items) > MAX_FURNITURE:
        raise Invalid(f"view.furniture: ожидается список до {MAX_FURNITURE} элементов")
    return [furniture_item(it) for it in items]


# ------------------------------------------------------------------ JSON ---
def _floors(s: Session, did: str) -> dict[int, Floor]:
    return {f.id: f for f in s.scalars(select(Floor).where(Floor.drawing_id == did))}


def _cand(floors: dict[int, Floor], fid: int | None) -> str:
    f = floors.get(fid) if fid is not None else None
    return (f.candidate or "") if f else ""


def placement_json(r: Placement, floors: dict[int, Floor]) -> dict:
    o = {"id": r.id, "floor": _cand(floors, r.floor_id), "item": r.item_id, "at": [r.x, r.y], "angle": r.angle}
    for k in ("size", "note", "elev", "fov", "range"):
        if (v := getattr(r, k)) is not None:
            o[k] = list(v) if k == "size" else v
    o["version"] = r.version
    if not o["floor"]:                              # its sheet is gone (or it never had a floor)
        f = floors.get(r.floor_id) if r.floor_id is not None else None
        o["_anchor"] = {"name": f.name} if f else None
    return o


def pin_json(r: Pin, floors: dict[int, Floor]) -> dict:
    return {"id": r.id, "floor": _cand(floors, r.floor_id), "pos": [r.x, r.y, r.z], "text": r.text,
            "label": r.label, "author": r.author, "created": r.created_at.timestamp(), "version": r.version}


def view_data(s: Session, did: str) -> dict:
    """furniture, furniture_unplaced, markers, comments of a drawing (only non-empty lists)."""
    floors = _floors(s, did)
    out: dict[str, list] = {"furniture": [], "furniture_unplaced": [], "markers": [], "comments": []}
    for r in s.scalars(select(Placement).where(Placement.drawing_id == did).order_by(Placement.created_at, Placement.id)):
        o = placement_json(r, floors)
        out["furniture" if o["floor"] else "furniture_unplaced"].append(o)
    for r in s.scalars(select(Pin).where(Pin.drawing_id == did).order_by(Pin.created_at, Pin.id)):
        out[r.kind + "s"].append(pin_json(r, floors))
    return {k: v for k, v in out.items() if v}


def _strip(o: dict | None) -> dict | None:
    return None if o is None else {k: v for k, v in o.items() if k not in ("version", "_anchor")}


# ---------------------------------------------------------------- writes ---
def _me_id() -> int | None:
    me = auth.current.get()
    return me.id if me else None


def audit_entry(s, pid, entity, eid, action, before, after, drawing_id=None):
    """Record a change by the user of the current request."""
    me = auth.current.get()
    s.add(AuditLog(project_id=pid, drawing_id=drawing_id, entity=entity, entity_id=eid, action=action,
                   user_id=me.id if me else None, actor=(me.login or None) if me else None,
                   before=_strip(before), after=_strip(after)))


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


def apply(s: Session, did: str, entity: str, ops: list, build: int | None = None, force: bool = False) -> dict:
    """Create / update / delete placements (entity 'placement') or pins ('pin').

    ops: [{"op": "create" | "update" | "delete", "id", "version", ...fields}]
    Updates and deletes must carry the version they were made against
    (unless `force`: the legacy whole-list PUT /view). All or nothing.
    Returns {"items": [changed rows as JSON], "deleted": [ids]}.
    """
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise Invalid(f"ops: ожидается список до {MAX_OPS} операций")
    Model = Placement if entity == "placement" else Pin
    d = lock_drawing(s, did, build)
    pid = d.project_id
    floors = _floors(s, did)
    by_cand = {f.candidate: f.id for f in floors.values() if f.candidate}
    ids = [o.get("id") for o in ops if isinstance(o, dict) and isinstance(o.get("id"), str)]
    rows = {r.id: r for r in s.scalars(select(Model).where(Model.drawing_id == did, Model.id.in_(ids)).with_for_update())}
    to_json = placement_json if Model is Placement else pin_json
    conflicts, changed, deleted = [], {}, []
    count = s.scalar(select(func.count()).select_from(Model).where(Model.drawing_id == did))
    limit = MAX_FURNITURE if Model is Placement else MAX_PINS * 2

    def floor_id(cand: str, allow_none: bool):
        if not cand and allow_none:
            return None
        if cand not in by_cand:
            raise Invalid(f"этаж «{cand}» не найден в текущей сборке")
        return by_cand[cand]

    for o in ops:
        if not isinstance(o, dict) or o.get("op") not in ("create", "update", "delete"):
            raise Invalid("ops: элемент {op: create | update | delete, id, version, ...}")
        op, row = o["op"], rows.get(o.get("id"))
        fields = {k: v for k, v in o.items() if k not in ("op", "version")}
        if op != "create" and not isinstance(o.get("id"), str):
            raise Invalid(f"ops: для {op} нужен id")
        if op == "create" and row is not None and not force:
            conflicts.append({"id": row.id, "current": to_json(row, floors)})
            continue
        if op != "create" and row is not None and not force and o.get("version") != row.version:
            conflicts.append({"id": row.id, "current": to_json(row, floors)})
            continue
        if op == "delete":
            if row is not None:
                audit_entry(s, pid, entity, row.id, "delete", to_json(row, floors), None, did)
                s.delete(row)
                rows.pop(row.id)
                deleted.append(row.id)
                count -= 1
            continue
        if op == "update" and row is None:
            if not force:
                conflicts.append({"id": o["id"], "current": None})
                continue
            op = "create"
        before = to_json(row, floors) if row is not None else None
        if Model is Placement:
            v = furniture_item({**(_strip(before) or {}), **fields})
            fid = floor_id(v["floor"], False) if (row is None or "floor" in fields) else row.floor_id
            if (row is None or v["item"] != row.item_id) and s.get(CatalogItem, v["item"]) is None:
                raise Invalid(f"предмета «{v['item']}» нет в каталоге")
            vals = {"floor_id": fid, "item_id": v["item"], "x": v["at"][0], "y": v["at"][1], "angle": v["angle"],
                    "size": v.get("size"), "note": v.get("note"), "elev": v.get("elev"), "fov": v.get("fov"),
                    "range": v.get("range")}
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
        if row is None:
            if count >= limit:
                raise Invalid(f"не больше {limit} объектов на чертеже")
            row = Model(drawing_id=did, id=v["id"], version=1, updated_by=_me_id(), **vals)
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


def replace(s: Session, did: str, key: str, value):
    """Legacy PUT /view: a whole list replaces the stored one (no versions)."""
    if key == "furniture":
        items = furniture(value)
        keep = {r.id for r in s.scalars(select(Placement).join(Floor, Placement.floor_id == Floor.id, isouter=True)
                                        .where(Placement.drawing_id == did,
                                               (Floor.candidate.is_(None)) | (Placement.floor_id.is_(None))))}
        current = set(s.scalars(select(Placement.id).where(Placement.drawing_id == did))) - keep
        ops = [{"op": "update", **it} for it in items]
        ops += [{"op": "delete", "id": i} for i in current - {it["id"] for it in items}]
        apply(s, did, "placement", ops, force=True)
    elif key == "furniture_unplaced":
        # only removal (after the items were put back on a floor or deleted): ids to keep
        if not isinstance(value, list):
            raise Invalid("view.furniture_unplaced: ожидается список")
        ids = {it.get("id") if isinstance(it, dict) else it for it in value}
        unplaced = view_data(s, did).get("furniture_unplaced") or []
        apply(s, did, "placement", [{"op": "delete", "id": u["id"]} for u in unplaced if u["id"] not in ids],
              force=True)
    else:
        items = pins(value, key)
        current = set(s.scalars(select(Pin.id).where(Pin.drawing_id == did, Pin.kind == PIN_KINDS[key])))
        ops = [{"op": "update", "kind": key, **it} for it in items]
        ops += [{"op": "delete", "id": i} for i in current - {it["id"] for it in items}]
        apply(s, did, "pin", ops, force=True)


def audit(s: Session, pid: str, limit: int = 100, drawing_id: str | None = None) -> list[dict]:
    """Changes in a project (or in one of its drawings), newest first."""
    q = select(AuditLog).where(AuditLog.project_id == pid)
    if drawing_id is not None:
        q = q.where(AuditLog.drawing_id == drawing_id)
    q = q.order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 1000))
    return [{"id": a.id, "at": a.at.timestamp(), "drawing_id": a.drawing_id, "entity": a.entity,
             "entity_id": a.entity_id, "action": a.action,
             "user_id": a.user_id, "actor": a.actor, "before": a.before, "after": a.after} for a in s.scalars(q)]
