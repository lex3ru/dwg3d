"""Layers of a project and the registry of layer kinds.

A layer kind says what its objects may be: geometry (points of catalog
items, polylines, polygons, routes), which catalog categories it takes, and
its default name. A new kind of layer is a new entry here — objects of all
kinds share one table (layer_objects) and keep kind-specific values in `props`.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CatalogItem, Layer, LayerObject

# categories: catalog categories accepted by point objects (None = any)
KINDS: dict[str, dict] = {
    "furniture": {"name": "Мебель и оборудование", "geoms": ("point",), "categories": None, "sort": 0},
    "cctv": {"name": "Видеонаблюдение", "geoms": ("point",), "categories": ("security",), "sort": 10},
    # functional layers (shapes.py): routes of people between rooms and floors, zones of floors
    "routes": {"name": "Маршруты людей", "geoms": ("route",), "categories": (), "sort": 20},
    "zones": {"name": "Зоны", "geoms": ("polygon",), "categories": (), "sort": 30},
    # engineering systems: equipment from their catalog categories; cable routes as polylines
    "network": {"name": "СКС и электрика", "geoms": ("point", "polyline"), "categories": ("network",), "sort": 40},
    "fire": {"name": "Пожарная сигнализация", "geoms": ("point",), "categories": ("fire",), "sort": 50},
    "access": {"name": "СКУД", "geoms": ("point",), "categories": ("access",), "sort": 60},
    "wifi": {"name": "Wi-Fi", "geoms": ("point",), "categories": ("wifi",), "sort": 70},
}
MAX_LAYERS = 200


class LayerError(ValueError):
    """Bad layer request (HTTP 400)."""


def kinds_json() -> list[dict]:
    return [{"kind": k, "name": v["name"], "geoms": list(v["geoms"]),
             "categories": list(v["categories"]) if v["categories"] is not None else None}
            for k, v in KINDS.items()]


def kinds_with_rules() -> dict:
    """GET /api/layer-kinds: the kinds and the rules of the functional layers."""
    from .shapes import rules_json
    return {"kinds": kinds_json(), **rules_json()}


def layer_json(layer: Layer, count: int | None = None) -> dict:
    o = {"id": layer.id, "kind": layer.kind, "name": layer.name, "visible": layer.visible,
         "locked": layer.locked, "sort": layer.sort, "props": layer.props or {}, "version": layer.version}
    if count is not None:
        o["count"] = count
    return o


def list_layers(s: Session, pid: str) -> list[dict]:
    counts = dict(s.execute(select(LayerObject.layer_id, func.count()).where(LayerObject.project_id == pid)
                            .group_by(LayerObject.layer_id)).all())
    q = select(Layer).where(Layer.project_id == pid).order_by(Layer.sort, Layer.created_at, Layer.id)
    return [layer_json(x, counts.get(x.id, 0)) for x in s.scalars(q)]


def _name(v, required: bool) -> str | None:
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > 120:
        raise LayerError("name: строка до 120 символов")
    return v.strip()


def create(s: Session, pid: str, v: dict, lid: str | None = None) -> Layer:
    """A new layer ({kind, name?, sort?}); `lid`: its id, when given in advance (a proposal)."""
    kind = v.get("kind")
    if kind not in KINDS:
        raise LayerError(f"kind: {', '.join(KINDS)}")
    if s.scalar(select(func.count()).select_from(Layer).where(Layer.project_id == pid)) >= MAX_LAYERS:
        raise LayerError(f"не больше {MAX_LAYERS} слоёв в проекте")
    name = _name(v.get("name"), False) or KINDS[kind]["name"]
    sort = v.get("sort")
    if sort is None:
        sort = (s.scalar(select(func.max(Layer.sort)).where(Layer.project_id == pid)) or 0) + 1
    if lid is not None and s.get(Layer, lid) is not None:
        raise LayerError(f"слой {lid} уже есть")
    layer = Layer(id=lid or uuid.uuid4().hex[:12], project_id=pid, kind=kind, name=name, sort=int(sort))
    s.add(layer)
    s.flush()
    return layer


def update(layer: Layer, v: dict) -> dict:
    """Apply name / visible / locked / sort / props; returns {field: (before, after)}."""
    changes = {}
    if "name" in v:
        changes["name"] = _name(v["name"], True)
    for key in ("visible", "locked"):
        if key in v:
            if not isinstance(v[key], bool):
                raise LayerError(f"{key}: true или false")
            changes[key] = v[key]
    if "sort" in v:
        if isinstance(v["sort"], bool) or not isinstance(v["sort"], int):
            raise LayerError("sort: целое число")
        changes["sort"] = v["sort"]
    if "props" in v:
        if not isinstance(v["props"], dict) or len(str(v["props"])) > 20000:
            raise LayerError("props: объект")
        changes["props"] = v["props"]
    out = {k: (getattr(layer, k), x) for k, x in changes.items() if getattr(layer, k) != x}
    for k, (_, x) in out.items():
        setattr(layer, k, x)
    if out:
        layer.version += 1
        layer.updated_at = func.now()
    return out


def default_layer(s: Session, pid: str, item_id: str | None, geom: str = "point") -> Layer:
    """The layer a new object goes to when none is given: for a catalog item
    the first layer of the most specific kind that takes its category, else
    the first layer of a kind that takes the geometry (created when the
    project has none)."""
    if geom == "point":
        cat = s.scalar(select(CatalogItem.category_id).where(CatalogItem.id == item_id)) if item_id else None
        kind = next((k for k, v in KINDS.items() if v["categories"] and cat in v["categories"]), "furniture")
    else:
        kind = next((k for k, v in KINDS.items() if geom in v["geoms"]), None)
        if kind is None:
            raise LayerError("нет типа слоя для такой геометрии: укажите слой")
    layer = s.scalar(select(Layer).where(Layer.project_id == pid, Layer.kind == kind)
                     .order_by(Layer.sort, Layer.created_at).limit(1))
    if layer is None:
        layer = create(s, pid, {"kind": kind, "sort": KINDS[kind]["sort"]})
    return layer


def accepts(layer: Layer, geom: str, category: str | None) -> str | None:
    """Why `layer` cannot hold such an object (None when it can)."""
    k = KINDS.get(layer.kind)
    if k is None:
        return f"неизвестный тип слоя «{layer.kind}»"
    if geom not in k["geoms"]:
        return f"слой «{layer.name}» не принимает такие объекты"
    if geom == "point" and k["categories"] is not None and category not in k["categories"]:
        return f"слой «{layer.name}» не принимает этот предмет каталога"
    return None


# ------------------------------------------------------------- variants ---
# A layer copied as a variant shares props.variant_group with its original
# (the id of the first layer of the group); each copied object keeps in
# props.origin the id of the object it goes back to (the first one of the
# chain), so objects of any two variants can be matched for comparison.
MAX_COPY = 20000
MOVED_M = 0.01


def variant_group(layer: Layer) -> str:
    return (layer.props or {}).get("variant_group") or layer.id


def copy_layer(s: Session, layer: Layer, name: str | None, lid: str | None = None, derived_ids: bool = False) -> Layer:
    """A variant: a copy of the layer with its objects. `lid`: the copy's id when given in
    advance; `derived_ids`: the copied objects get "<original id>-<the copy's id[:6]>" (a
    proposal changes them in the same breath), else random ids."""
    from .viewdata import MAX_OBJECTS

    objs = list(s.scalars(select(LayerObject).where(LayerObject.layer_id == layer.id)))
    if len(objs) > MAX_COPY:
        raise LayerError(f"слой слишком большой для копии (больше {MAX_COPY} объектов)")
    per_drawing: dict[str, int] = {}
    for o in objs:
        per_drawing[o.drawing_id] = per_drawing.get(o.drawing_id, 0) + 1
    for did, n in per_drawing.items():
        have = s.scalar(select(func.count()).select_from(LayerObject).where(LayerObject.drawing_id == did))
        if have + n > MAX_OBJECTS:
            raise LayerError(f"на чертеже не поместится ещё {n} объектов (не больше {MAX_OBJECTS})")
    group = variant_group(layer)
    if (layer.props or {}).get("variant_group") != group:
        layer.props = {**(layer.props or {}), "variant_group": group}
    n_variants = s.scalar(select(func.count()).select_from(Layer).where(
        Layer.project_id == layer.project_id, (Layer.id == group) | (Layer.props["variant_group"].astext == group)))
    base = layer.name.split(" — вариант")[0]
    copy = create(s, layer.project_id, {"kind": layer.kind, "name": _name(name, False) or f"{base} — вариант {n_variants + 1}",
                                        "sort": layer.sort}, lid)
    copy.props = {**(layer.props or {}), "variant_group": group}
    taken = set(s.scalars(select(LayerObject.id).where(LayerObject.project_id == layer.project_id)))
    for o in objs:
        oid = f"{o.id}-{copy.id[:6]}" if derived_ids else uuid.uuid4().hex[:8]
        if len(oid) > 40:
            oid = uuid.uuid4().hex[:8]
        while oid in taken:
            oid = uuid.uuid4().hex[:8]
        taken.add(oid)
        s.add(LayerObject(project_id=o.project_id, id=oid, layer_id=copy.id, drawing_id=o.drawing_id, floor_id=o.floor_id,
                          room_id=o.room_id, item_id=o.item_id, geom=o.geom, x=o.x, y=o.y, angle=o.angle,
                          points=o.points, size=o.size, elev=o.elev, note=o.note,
                          props={**(o.props or {}), "origin": (o.props or {}).get("origin") or o.id}, version=1))
    s.flush()
    return copy


def _key(o: LayerObject) -> str:
    return (o.props or {}).get("origin") or o.id


def compare(s: Session, a: Layer, b: Layer) -> dict:
    """What differs between two layers (variants): objects added, removed,
    moved or changed from `a` to `b`, and the specification of both."""
    from .models import CatalogCategory, CatalogItem, Drawing, Floor, Room

    oa = {_key(o): o for o in s.scalars(select(LayerObject).where(LayerObject.layer_id == a.id))}
    ob = {_key(o): o for o in s.scalars(select(LayerObject).where(LayerObject.layer_id == b.id))}
    items = {i.id: i for i in s.scalars(select(CatalogItem).where(
        CatalogItem.id.in_({o.item_id for o in [*oa.values(), *ob.values()] if o.item_id})))}
    cats = {c.id: c for c in s.scalars(select(CatalogCategory))}
    floor_ids = {o.floor_id for o in [*oa.values(), *ob.values()] if o.floor_id}
    floors = {f.id: f for f in s.scalars(select(Floor).where(Floor.id.in_(floor_ids)))} if floor_ids else {}
    room_ids = {o.room_id for o in [*oa.values(), *ob.values()] if o.room_id}
    rooms = {r.id: r for r in s.scalars(select(Room).where(Room.id.in_(room_ids)))} if room_ids else {}
    drawings = {d.id: d for d in s.scalars(select(Drawing).where(Drawing.project_id == a.project_id))}

    def name(o: LayerObject) -> str:
        if o.item_id:
            return items[o.item_id].name if o.item_id in items else o.item_id
        p = o.props or {}
        return p.get("name") or {"route": "Маршрут", "polygon": "Зона"}.get(o.geom, "Объект")

    def where(o: LayerObject) -> dict:
        f, r, d = floors.get(o.floor_id), rooms.get(o.room_id), drawings.get(o.drawing_id)
        return {"drawing_id": o.drawing_id, "drawing": (d.name or d.filename.rsplit(".", 1)[0]) if d else "",
                "floor": (f.candidate or "") if f else "", "floor_name": f.name if f else "",
                "room": (r.name or "без названия") if r else "", "at": [round(o.x, 3), round(o.y, 3)]}

    def diff(x: LayerObject, y: LayerObject) -> list[str]:
        what = []
        if x.drawing_id != y.drawing_id or x.floor_id != y.floor_id:
            what.append("этаж")
        elif abs(x.x - y.x) > MOVED_M or abs(x.y - y.y) > MOVED_M or (x.points or []) != (y.points or []):
            what.append("положение")
        if abs((x.angle or 0) - (y.angle or 0)) > 0.01:
            what.append("поворот")
        if x.item_id != y.item_id:
            what.append("предмет")
        if (x.size or None) != (y.size or None) or x.elev != y.elev:
            what.append("размер")
        px = {k: v for k, v in (x.props or {}).items() if k != "origin"}
        py = {k: v for k, v in (y.props or {}).items() if k != "origin"}
        if px != py:
            what.append("параметры")
        if (x.note or "") != (y.note or ""):
            what.append("примечание")
        return what

    objects, counts = [], {"added": 0, "removed": 0, "moved": 0, "changed": 0, "same": 0}
    for k in sorted(set(oa) | set(ob)):
        x, y = oa.get(k), ob.get(k)
        if x is None:
            ch, what, o = "added", [], y
        elif y is None:
            ch, what, o = "removed", [], x
        else:
            what = diff(x, y)
            ch = "same" if not what else "moved" if set(what) <= {"положение", "поворот", "этаж"} else "changed"
            o = y
        counts[ch] += 1
        if ch != "same" and len(objects) < 1000:
            objects.append({"key": k, "change": ch, "what": what, "id_a": x.id if x else None, "id_b": y.id if y else None,
                            "item": o.item_id, "name": name(o), "geom": o.geom, **where(o),
                            **({"from": where(x)} if ch == "moved" and x is not None else {})})

    spec: dict[str, dict] = {}
    for side, objs in (("a", oa), ("b", ob)):
        for o in objs.values():
            if not o.item_id:
                continue
            it = items.get(o.item_id)
            r = spec.setdefault(o.item_id, {
                "item": o.item_id, "name": it.name if it else o.item_id,
                "category": cats[it.category_id].name if it and it.category_id in cats else "",
                "price": float(it.price) if it and it.price is not None else None,
                "currency": it.currency if it and it.price is not None else None, "qty_a": 0, "qty_b": 0})
            r[f"qty_{side}"] += 1
    totals: dict[str, dict[str, float]] = {}
    rows = sorted(spec.values(), key=lambda r: (r["category"], r["name"]))
    for r in rows:
        r["delta"] = r["qty_b"] - r["qty_a"]
        if r["price"] is not None:
            r["sum_a"], r["sum_b"] = round(r["price"] * r["qty_a"], 2), round(r["price"] * r["qty_b"], 2)
            t = totals.setdefault(r["currency"], {"a": 0.0, "b": 0.0})
            t["a"] += r["sum_a"]
            t["b"] += r["sum_b"]
    return {"a": layer_json(a, len(oa)), "b": layer_json(b, len(ob)), "counts": counts, "objects": objects,
            "items": rows, "totals": {c: {"a": round(t["a"], 2), "b": round(t["b"], 2), "delta": round(t["b"] - t["a"], 2)}
                                      for c, t in totals.items()}}
