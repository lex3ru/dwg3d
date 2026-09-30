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
}
MAX_LAYERS = 200


class LayerError(ValueError):
    """Bad layer request (HTTP 400)."""


def kinds_json() -> list[dict]:
    return [{"kind": k, "name": v["name"], "geoms": list(v["geoms"]),
             "categories": list(v["categories"]) if v["categories"] is not None else None}
            for k, v in KINDS.items()]


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


def create(s: Session, pid: str, v: dict) -> Layer:
    kind = v.get("kind")
    if kind not in KINDS:
        raise LayerError(f"kind: {', '.join(KINDS)}")
    if s.scalar(select(func.count()).select_from(Layer).where(Layer.project_id == pid)) >= MAX_LAYERS:
        raise LayerError(f"не больше {MAX_LAYERS} слоёв в проекте")
    name = _name(v.get("name"), False) or KINDS[kind]["name"]
    sort = v.get("sort")
    if sort is None:
        sort = (s.scalar(select(func.max(Layer.sort)).where(Layer.project_id == pid)) or 0) + 1
    layer = Layer(id=uuid.uuid4().hex[:12], project_id=pid, kind=kind, name=name, sort=int(sort))
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


def default_layer(s: Session, pid: str, item_id: str | None) -> Layer:
    """The layer a new catalog object goes to when none is given: the first
    layer of the most specific kind that takes the item's category (created
    when the project has none)."""
    cat = s.scalar(select(CatalogItem.category_id).where(CatalogItem.id == item_id)) if item_id else None
    kind = next((k for k, v in KINDS.items() if v["categories"] and cat in v["categories"]), "furniture")
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
