"""Furniture / equipment catalog stored in PostgreSQL.

`catalog_seed.yaml` is the editable source until the catalog editor exists:
`load()` upserts it by id (items dropped from the file become inactive, never
deleted: placed furniture keeps referring to them); the API seeds an empty
catalog on start-up.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import func, select, update

from . import db
from .models import CatalogCategory, CatalogItem

SEED = Path(__file__).with_name("catalog_seed.yaml")
ITEM_FIELDS = ("name", "w", "d", "h", "elev", "clear", "wall", "kind", "color", "model", "model_rot",
               "tags", "article", "supplier", "price", "currency")


class CatalogError(ValueError):
    pass


def _parse(path: Path) -> tuple[list[dict], list[dict]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cats, items, seen = [], [], set()
    for ci, c in enumerate(data.get("categories") or []):
        if not isinstance(c, dict) or not c.get("id") or not c.get("name"):
            raise CatalogError(f"категория #{ci + 1}: нужны id и name")
        cats.append({"id": str(c["id"]), "name": str(c["name"]), "color": str(c.get("color") or "#868e96"),
                     "sort": ci})
        for it in c.get("items") or []:
            iid = str((it or {}).get("id") or "")
            where = f"{c['id']} / {iid or '?'}"
            if not iid or not it.get("name") or not it.get("kind"):
                raise CatalogError(f"{where}: нужны id, name и kind")
            if iid in seen:
                raise CatalogError(f"{where}: id повторяется")
            seen.add(iid)
            unknown = set(it) - set(ITEM_FIELDS) - {"id", "cam"}
            if unknown:
                raise CatalogError(f"{where}: неизвестные поля {sorted(unknown)}")
            for k in ("w", "d", "h"):
                if not isinstance(it.get(k), (int, float)) or not 0 < it[k] <= 50:
                    raise CatalogError(f"{where}: {k} — число от 0 до 50 м")
            cam = it.get("cam")
            if cam is not None and not (isinstance(cam, dict) and
                                        all(isinstance(cam.get(k), (int, float)) for k in ("fov", "range", "ident"))):
                raise CatalogError(f"{where}: cam — {{fov, range, ident}}")
            row = {k: it.get(k) for k in ITEM_FIELDS}
            row.update(id=iid, category_id=cats[-1]["id"], camera=cam, wall=bool(it.get("wall")),
                       currency=str(it.get("currency") or "RUB"), sort=len(items), active=True)
            items.append(row)
    if not items:
        raise CatalogError(f"{path}: в каталоге нет позиций")
    return cats, items


def load(path: Path = SEED) -> dict:
    """Upsert the catalog from YAML; returns counts."""
    cats, items = _parse(Path(path))
    ids = [r["id"] for r in items]
    with db.session() as s:
        for r in cats:
            s.merge(CatalogCategory(**r))
        s.flush()
        existing = set(s.scalars(select(CatalogItem.id)))
        for r in items:
            s.merge(CatalogItem(**r, updated_at=func.now()))
        gone = s.execute(update(CatalogItem).where(CatalogItem.id.not_in(ids), CatalogItem.active)
                         .values(active=False, updated_at=func.now())).rowcount
    return {"categories": len(cats), "items": len(items), "added": len(set(ids) - existing), "deactivated": gone}


def ensure_seeded():
    with db.session() as s:
        empty = not s.scalar(select(func.count()).select_from(CatalogItem))
    if empty:
        load(SEED)


def as_json() -> dict:
    """Catalog in the shape the viewer uses (frontend/src/furniture/catalog.ts)."""
    with db.session() as s:
        cats = s.scalars(select(CatalogCategory).order_by(CatalogCategory.sort, CatalogCategory.id)).all()
        items = s.scalars(select(CatalogItem).order_by(CatalogItem.sort, CatalogItem.id)).all()
    out = []
    for i in items:
        o = {"id": i.id, "name": i.name, "cat": i.category_id, "w": i.w, "d": i.d, "h": i.h, "kind": i.kind}
        for k, v in (("color", i.color), ("clear", i.clear), ("elev", i.elev), ("model", i.model),
                     ("modelRot", i.model_rot), ("tags", i.tags), ("cam", i.camera), ("article", i.article),
                     ("supplier", i.supplier)):
            if v is not None:
                o[k] = v
        if i.wall:
            o["wall"] = True
        if i.price is not None:
            o["price"] = float(i.price)
            o["currency"] = i.currency
        if not i.active:
            o["active"] = False
        out.append(o)
    return {"categories": [{"id": c.id, "name": c.name, "color": c.color} for c in cats], "items": out}
