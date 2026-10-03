"""Layers of a project (see layers.py): variants of the furniture and engineering systems."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from .. import access, auth, db, layers, store, viewdata
from ..models import LayerObject
from . import common

router = APIRouter()


@router.get("/api/layer-kinds")
def layer_kinds():
    """{kinds, flows, flow_conflicts, zone_kinds, zone_forbidden}: layer kinds and the rules of routes and zones."""
    return layers.kinds_with_rules()


@router.get("/api/projects/{pid}/layers")
def list_layers(pid: str):
    with db.session() as s:
        common.project(s, pid)
        shown = access.visible_layers(auth.current.get())
        return [x for x in layers.list_layers(s, pid) if shown is None or x["id"] in shown]


@router.post("/api/projects/{pid}/layers", status_code=201)
def create_layer(pid: str, v: dict):
    with db.session() as s:
        common.project(s, pid, lock=True)
        layer = layers.create(s, pid, v)
        viewdata.audit_entry(s, pid, "layer", layer.id, "create", None, layers.layer_json(layer))
        store.touch_project(s, pid)
        return layers.layer_json(layer, 0)


@router.patch("/api/projects/{pid}/layers/{lid}")
def update_layer(pid: str, lid: str, v: dict):
    with db.session() as s:
        common.project(s, pid)
        layer = common.layer(s, pid, lid)
        if "version" in v and v["version"] != layer.version:
            raise viewdata.Conflict("Слой изменён другим пользователем: обновите данные и повторите",
                                    [{"id": lid, "current": layers.layer_json(layer)}])
        changes = layers.update(layer, v)
        if changes:
            viewdata.audit_entry(s, pid, "layer", lid, "update", {k: b for k, (b, _) in changes.items()},
                                 {k: a for k, (_, a) in changes.items()})
            store.touch_project(s, pid)
        return layers.layer_json(layer)


@router.post("/api/projects/{pid}/layers/{lid}/copy", status_code=201)
def copy_layer(pid: str, lid: str, v: dict | None = None):
    """A copy of the layer with all its objects: a variant to compare with it."""
    with db.session() as s:
        common.project(s, pid, lock=True)
        layer = common.layer(s, pid, lid)
        copy = layers.copy_layer(s, layer, (v or {}).get("name"))
        viewdata.audit_entry(s, pid, "layer", copy.id, "create", None, {**layers.layer_json(copy), "copy_of": lid})
        store.touch_project(s, pid)
        n = s.scalar(select(func.count()).select_from(LayerObject).where(LayerObject.layer_id == copy.id))
        return layers.layer_json(copy, n)


@router.get("/api/projects/{pid}/layers/compare")
def compare_layers(pid: str, a: str, b: str):
    """Differences between two layers (variants): objects and the specification."""
    with db.session() as s:
        common.project(s, pid)
        la, lb = common.layer_of(s, pid, a), common.layer_of(s, pid, b)
        shown = access.visible_layers(auth.current.get())
        if la is None or lb is None or (shown is not None and not {a, b} <= shown):
            raise HTTPException(404, "Слой не найден")
        return layers.compare(s, la, lb)


@router.delete("/api/projects/{pid}/layers/{lid}", status_code=204)
def delete_layer(pid: str, lid: str):
    """The layer and all its objects."""
    with db.session() as s:
        common.project(s, pid)
        layer = common.layer(s, pid, lid)
        if layer.locked:
            raise HTTPException(409, f"Слой «{layer.name}» заблокирован")
        viewdata.audit_entry(s, pid, "layer", lid, "delete", layers.layer_json(layer), None)
        s.delete(layer)
        store.touch_project(s, pid)
