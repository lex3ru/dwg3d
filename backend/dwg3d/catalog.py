"""Furniture / equipment catalog stored in PostgreSQL.

The catalog is edited in the viewer (catalog_admin role) through
/api/catalog/...; `catalog_seed.yaml` seeds an empty database on start-up.
`load()` imports a YAML file (upsert by id; with `prune`, items missing from
the file are deactivated) and `dump()` writes the database back in the same
format (backup, review, moving between servers). Items are never deleted:
placed furniture keeps referring to them; `active = false` hides an item
from the picker.

GLB models: the bundled ones live in frontend/public/catalog/ (model
"kenney/x.glb" -> /catalog/kenney/x.glb); uploaded ones in the file store
(files.py, key catalog/<file>; model "upload/<file>" -> /api/catalog/models/<file>).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from sqlalchemy import func, select, update

from . import db, files
from .models import CatalogCategory, CatalogItem

SEED = Path(__file__).with_name("catalog_seed.yaml")
ITEM_FIELDS = ("name", "w", "d", "h", "elev", "clear", "wall", "kind", "color", "model", "model_rot",
               "tags", "article", "supplier", "price", "currency")
UPLOAD = "upload/"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,59}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9_./-]{1,200}\.glb$")
# API / viewer names -> columns
ALIASES = {"cat": "category", "modelRot": "model_rot", "camera": "cam"}


class CatalogError(ValueError):
    pass


# ------------------------------------------------------------ validation ---
def _num(v, lo, hi, where, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise CatalogError(f"{where}: {name} — число от {lo} до {hi}")
    return float(v)


def _str(v, n, where, name):
    if not isinstance(v, str) or len(v) > n:
        raise CatalogError(f"{where}: {name} — строка до {n} символов")
    return v.strip()


def clean_item(it: dict, where: str) -> dict:
    """Validated column values of an item (YAML entry or API body, all fields)."""
    if not isinstance(it, dict):
        raise CatalogError(f"{where}: ожидается объект")
    it = {ALIASES.get(k, k): v for k, v in it.items()}
    unknown = set(it) - set(ITEM_FIELDS) - {"id", "cam", "category", "active", "sort"}
    if unknown:
        raise CatalogError(f"{where}: неизвестные поля {sorted(unknown)}")
    name, kind = it.get("name"), it.get("kind")
    if not name or not kind:
        raise CatalogError(f"{where}: нужны name и kind")
    row = {"name": _str(name, 200, where, "name"), "kind": _str(kind, 40, where, "kind"),
           "w": _num(it.get("w"), 0.01, 50, where, "w"), "d": _num(it.get("d"), 0.01, 50, where, "d"),
           "h": _num(it.get("h"), 0.01, 50, where, "h"), "wall": bool(it.get("wall"))}
    opt = {"elev": lambda v: _num(v, 0, 20, where, "elev"), "clear": lambda v: _num(v, 0, 5, where, "clear"),
           "model_rot": lambda v: _num(v, -360, 360, where, "model_rot"),
           "tags": lambda v: _str(v, 500, where, "tags"), "article": lambda v: _str(v, 100, where, "article"),
           "supplier": lambda v: _str(v, 200, where, "supplier"),
           "price": lambda v: _num(v, 0, 1e10, where, "price")}
    for k, f in opt.items():
        v = it.get(k)
        row[k] = None if v is None or v == "" else f(v)
    color = it.get("color")
    if color not in (None, "") and not (isinstance(color, str) and COLOR_RE.match(color)):
        raise CatalogError(f"{where}: color — #rrggbb")
    row["color"] = color or None
    model = it.get("model")
    if model not in (None, "") and not (isinstance(model, str) and MODEL_RE.match(model) and ".." not in model):
        raise CatalogError(f"{where}: model — путь к .glb")
    row["model"] = model or None
    cur = it.get("currency") or "RUB"
    if not (isinstance(cur, str) and re.fullmatch(r"[A-Z]{3}", cur)):
        raise CatalogError(f"{where}: currency — три заглавные буквы (RUB, EUR…)")
    row["currency"] = cur
    cam = it.get("cam")
    if cam is not None:
        if not isinstance(cam, dict):
            raise CatalogError(f"{where}: cam — {{fov, range, ident}}")
        cam = {"fov": _num(cam.get("fov"), 1, 360, where, "cam.fov"),
               "range": _num(cam.get("range"), 0.5, 300, where, "cam.range"),
               "ident": _num(cam.get("ident"), 0, 300, where, "cam.ident")}
    row["camera"] = cam
    if "active" in it:
        row["active"] = bool(it["active"])
    return row


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
            if not iid:
                raise CatalogError(f"{where}: нужен id")
            if iid in seen:
                raise CatalogError(f"{where}: id повторяется")
            seen.add(iid)
            row = clean_item(it, where)
            row.setdefault("active", True)
            row.update(id=iid, category_id=cats[-1]["id"], sort=len(items))
            items.append(row)
    if not items:
        raise CatalogError(f"{path}: в каталоге нет позиций")
    return cats, items


# ------------------------------------------------------------ YAML files ---
def load(path: Path = SEED, prune: bool = False) -> dict:
    """Import a YAML catalog (upsert by id). With `prune`, items missing from
    the file are deactivated (never deleted); by default they are kept, so
    items added in the editor survive importing an older file."""
    cats, items = _parse(Path(path))
    ids = [r["id"] for r in items]
    with db.session() as s:
        for r in cats:
            s.merge(CatalogCategory(**r))
        s.flush()
        existing = set(s.scalars(select(CatalogItem.id)))
        for r in items:
            s.merge(CatalogItem(**r, updated_at=func.now()))
        gone = 0
        if prune:
            gone = s.execute(update(CatalogItem).where(CatalogItem.id.not_in(ids), CatalogItem.active)
                             .values(active=False, updated_at=func.now())).rowcount
    return {"categories": len(cats), "items": len(items), "added": len(set(ids) - existing), "deactivated": gone}


def dump(path: Path) -> dict:
    """Write the database catalog as YAML in the seed format."""
    data = as_json()
    by_cat: dict[str, list] = {c["id"]: [] for c in data["categories"]}
    back = {"cat": None, "modelRot": "model_rot", "modelUrl": None, "sort": None}
    for it in data["items"]:
        row = {back.get(k, k): v for k, v in it.items() if back.get(k, k)}
        by_cat.setdefault(it["cat"], []).append(row)
    out = {"categories": [{**c, "items": by_cat.get(c["id"], [])} for c in data["categories"]]}
    Path(path).write_text("# Catalog exported from the database (python -m dwg3d catalog dump)\n\n" +
                          yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    return {"categories": len(out["categories"]), "items": len(data["items"])}


def ensure_seeded():
    with db.session() as s:
        empty = not s.scalar(select(func.count()).select_from(CatalogItem))
    if empty:
        load(SEED)


# ------------------------------------------------------------------ JSON ---
def model_url(model: str | None) -> str | None:
    if not model:
        return None
    return f"/api/catalog/models/{model[len(UPLOAD):]}" if model.startswith(UPLOAD) else f"/catalog/{model}"


def item_json(i: CatalogItem) -> dict:
    o = {"id": i.id, "name": i.name, "cat": i.category_id, "w": i.w, "d": i.d, "h": i.h, "kind": i.kind}
    for k, v in (("color", i.color), ("clear", i.clear), ("elev", i.elev), ("model", i.model),
                 ("modelRot", i.model_rot), ("tags", i.tags), ("cam", i.camera), ("article", i.article),
                 ("supplier", i.supplier)):
        if v is not None:
            o[k] = v
    if i.model:
        o["modelUrl"] = model_url(i.model)
    if i.wall:
        o["wall"] = True
    if i.price is not None:
        o["price"] = float(i.price)
        o["currency"] = i.currency
    if not i.active:
        o["active"] = False
    return o


def as_json() -> dict:
    """Catalog in the shape the viewer uses (frontend/src/furniture/catalog.ts)."""
    with db.session() as s:
        cats = s.scalars(select(CatalogCategory).order_by(CatalogCategory.sort, CatalogCategory.id)).all()
        items = s.scalars(select(CatalogItem).order_by(CatalogItem.sort, CatalogItem.id)).all()
    return {"categories": [{"id": c.id, "name": c.name, "color": c.color} for c in cats],
            "items": [item_json(i) for i in items]}


# ----------------------------------------------------------------- edits ---
def _audit(s, eid: str, action: str, before, after):
    from .viewdata import audit_entry       # avoid an import cycle (viewdata -> catalog items)
    audit_entry(s, None, "catalog_item", eid, action, before, after)


def _category(s, cid) -> CatalogCategory:
    c = s.get(CatalogCategory, cid) if isinstance(cid, str) else None
    if c is None:
        raise CatalogError(f"категории «{cid}» нет")
    return c


def create_item(v: dict) -> dict:
    iid = v.get("id")
    if not isinstance(iid, str) or not ID_RE.match(iid):
        raise CatalogError("id — латиница, цифры, «.», «_», «-» (например, diag.mri2)")
    row = clean_item({k: x for k, x in v.items() if k != "id"}, iid)
    with db.session() as s:
        cat = _category(s, v.get("cat") or v.get("category"))
        if s.get(CatalogItem, iid) is not None:
            raise CatalogError(f"позиция «{iid}» уже есть")
        sort = (s.scalar(select(func.max(CatalogItem.sort))) or 0) + 1
        row.setdefault("active", True)
        item = CatalogItem(id=iid, category_id=cat.id, sort=sort, **row)
        s.add(item)
        s.flush()
        out = item_json(item)
        _audit(s, iid, "create", None, out)
        return out


def update_item(iid: str, v: dict) -> dict:
    """Partial update: fields given replace the stored ones (null clears an optional one)."""
    with db.session() as s:
        item = s.get(CatalogItem, iid, with_for_update=True)
        if item is None:
            raise LookupError(iid)
        before = item_json(item)
        merged = {k: x for k, x in before.items() if k not in ("id", "modelUrl")}
        merged.update({k: x for k, x in v.items() if k != "id"})
        row = clean_item({k: x for k, x in merged.items() if k != "cat"}, iid)
        cat = _category(s, merged.get("cat") or merged.get("category"))
        for k, x in row.items():
            setattr(item, k, x)
        item.category_id = cat.id
        item.updated_at = func.now()
        s.flush()
        out = item_json(item)
        if out != before:
            _audit(s, iid, "update", before, out)
        return out


def upload_model(iid: str, data: bytes) -> dict:
    """Store a GLB for the item (content-addressed file name) and point the item to it."""
    if data[:4] != b"glTF" or int.from_bytes(data[4:8], "little") != 2:
        raise CatalogError("нужен файл GLB (glTF 2.0, бинарный)")
    name = f"{iid.replace('/', '_')}-{hashlib.sha256(data).hexdigest()[:12]}.glb"
    files.store().put_bytes(model_key(name), data, "model/gltf-binary")
    return update_item(iid, {"model": UPLOAD + name})


def model_key(name: str) -> str | None:
    """File-store key of an uploaded model, None for a name that is not one."""
    return f"catalog/{name}" if re.fullmatch(r"[A-Za-z0-9_.-]{1,200}\.glb", name) and ".." not in name else None


def save_category(cid: str, v: dict, create: bool) -> dict:
    if create and (not isinstance(cid, str) or not ID_RE.match(cid)):
        raise CatalogError("id категории — латиница, цифры, «.», «_», «-»")
    name, color = v.get("name"), v.get("color")
    with db.session() as s:
        c = s.get(CatalogCategory, cid)
        if create and c is not None:
            raise CatalogError(f"категория «{cid}» уже есть")
        if not create and c is None:
            raise LookupError(cid)
        if c is None:
            c = CatalogCategory(id=cid, name="", color="#868e96",
                                sort=(s.scalar(select(func.max(CatalogCategory.sort))) or 0) + 1)
            s.add(c)
        if name is not None or create:
            c.name = _str(name or "", 120, cid, "name")
            if not c.name:
                raise CatalogError(f"{cid}: нужно название")
        if color is not None:
            if not (isinstance(color, str) and COLOR_RE.match(color)):
                raise CatalogError(f"{cid}: color — #rrggbb")
            c.color = color
        if "sort" in v:
            c.sort = int(_num(v["sort"], -1e6, 1e6, cid, "sort"))
        s.flush()
        return {"id": c.id, "name": c.name, "color": c.color}
