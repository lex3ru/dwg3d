"""Перенос здания на другую установку: часть каталога (типы, модели, слои, наборы, назначения),
которой пользуются предметы и единицы здания. Ключи в пакете — id на исходной установке;
на новой всё сопоставляется по названию, недостающее заводится. Существующее не меняется —
только к найденному типу добавляются его характеристики «у каждой вещи», которых на новой
установке нет, чтобы значения единиц не потерялись."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.modules.catalog import api
from app.modules.catalog.models import (
    Characteristic,
    CharSet,
    ItemType,
    Layer,
    Model,
    Purpose,
    TypeSet,
)

CHAR_FIELDS = ("name", "kind", "unit", "choices", "level", "required", "note")


def _char(c: Characteristic) -> dict[str, Any]:
    return {f: getattr(c, f) for f in CHAR_FIELDS}


def _named(chars: dict[uuid.UUID, Characteristic], values: dict[uuid.UUID, Any]) -> dict[str, Any]:
    return {chars[k].name: v for k, v in values.items() if k in chars}


def export(
    session: Session, type_ids: set[uuid.UUID], model_ids: set[uuid.UUID], purpose_ids: set[str]
) -> tuple[dict[str, Any], list[uuid.UUID]]:
    """Часть каталога для пакета и id файлов (3D-модели), которые нужно положить рядом."""
    types = [t for t in session.scalars(select(ItemType).where(ItemType.id.in_(type_ids)))]
    files: list[uuid.UUID] = []
    layer_ids = {t.layer_id for t in types if t.layer_id}
    sets: dict[uuid.UUID, CharSet] = {}
    out_types = []
    for t in types:
        chars = {c.id: c for c in api.characteristics_of(session, t)}
        set_ids = list(session.scalars(select(TypeSet.set_id).where(TypeSet.type_id == t.id)))
        for s in set_ids:
            sets[s] = session.get(CharSet, s)  # type: ignore[assignment]
        own = session.scalars(
            select(Characteristic)
            .where(Characteristic.type_id == t.id)
            .order_by(Characteristic.position)
        )
        if t.model_file_id:
            files.append(t.model_file_id)
        out_types.append(
            {
                "key": str(t.id),
                "name": t.name,
                "layer": str(t.layer_id) if t.layer_id else None,
                **{
                    f: getattr(t, f)
                    for f in (
                        "width",
                        "depth",
                        "height",
                        "mount",
                        "mount_height",
                        "top_view",
                        "icon",
                        "accounting",
                        "unit",
                        "life_months",
                        "container",
                    )
                },
                "price": float(t.price) if t.price is not None else None,
                "sets": [sets[s].name for s in set_ids],
                "characteristics": [_char(c) for c in own],
                "values": _named(chars, api.values_of(session, type_id=t.id)),
                "model3d": {
                    "file": str(t.model_file_id),
                    "size": t.model_size,
                    "credit": t.model_credit or "",
                    "transform": t.model_transform or {},
                }
                if t.model_file_id
                else None,
                # характеристики «у каждой вещи» — по ним сопоставляются значения единиц
                "item_chars": {str(c.id): c.name for c in chars.values() if c.level == "item"},
            }
        )
    models = []
    for m in session.scalars(select(Model).where(Model.id.in_(model_ids))):
        t = session.get(ItemType, m.type_id)
        chars = {c.id: c for c in api.characteristics_of(session, t)} if t else {}
        models.append(
            {
                "key": str(m.id),
                "type": str(m.type_id),
                "manufacturer": m.manufacturer,
                "name": m.name,
                "article": m.article,
                "supplier": m.supplier,
                "price": float(m.price) if m.price is not None else None,
                "values": _named(chars, api.values_of(session, model_id=m.id)),
            }
        )
    layers = [
        {
            "key": str(la.id),
            "name": la.name,
            "color": la.color,
            "icon": la.icon,
            "note": la.note,
            "visible": la.visible,
        }
        for la in session.scalars(select(Layer).where(Layer.id.in_(layer_ids)))
    ]
    out_sets = [
        {
            "name": s.name,
            "characteristics": [
                _char(c) for c in sorted(s.characteristics, key=lambda c: c.position)
            ],
        }
        for s in sets.values()
    ]
    wanted = {uuid.UUID(p) for p in purpose_ids if p}
    purposes = [
        {"key": str(p.id), "name": p.name, "surface": p.surface, "norm": p.norm, "note": p.note}
        for p in session.scalars(select(Purpose).where(Purpose.id.in_(wanted)))
    ]
    return (
        {
            "layers": layers,
            "sets": out_sets,
            "types": out_types,
            "models": models,
            "purposes": purposes,
        },
        files,
    )


def _find(session: Session, cls: Any, name: str, *where: Any) -> Any:
    q = select(cls).where(func.lower(cls.name) == name.strip().lower(), *where)
    found = list(session.scalars(q))
    live = [x for x in found if getattr(x, "archived_at", None) is None]
    return (live or found or [None])[0]


def load(
    session: Session, actor: Actor, data: dict[str, Any], files: dict[str, uuid.UUID], apply: bool
) -> dict[str, Any]:
    """Сопоставить или (apply) завести. Возвращает отчёт и соответствия ключей пакета id
    новой установки: types, models, purposes, item_chars {(ключ типа, ключ характеристики)}."""
    report: dict[str, list[str]] = {
        "layers": [],
        "sets": [],
        "types": [],
        "models": [],
        "purposes": [],
        "characteristics": [],
    }
    maps: dict[str, dict[Any, Any]] = {"types": {}, "models": {}, "purposes": {}, "item_chars": {}}
    layers: dict[str, uuid.UUID | None] = {}
    for la in data.get("layers", []):
        found = _find(session, Layer, la["name"])
        if found is None:
            report["layers"].append(la["name"])
            if apply:
                found = api.create_layer(
                    session,
                    actor,
                    {k: la[k] for k in ("name", "color", "icon", "note", "visible") if k in la},
                )
        layers[la["key"]] = found.id if found else None
    sets: dict[str, uuid.UUID | None] = {}
    for s in data.get("sets", []):
        found = _find(session, CharSet, s["name"])
        if found is None:
            report["sets"].append(s["name"])
            if apply:
                found = api.create_set(session, actor, s["name"])
                for c in s.get("characteristics", []):
                    api.create_characteristic(session, actor, {**c, "set_id": found.id})
        sets[s["name"]] = found.id if found else None
    for p in data.get("purposes", []):
        found = _find(session, Purpose, p["name"])
        if found is None:
            report["purposes"].append(p["name"])
            if apply:
                found = api.create_purpose(
                    session, actor, {k: p[k] for k in ("name", "surface", "norm", "note") if k in p}
                )
        maps["purposes"][p["key"]] = str(found.id) if found else None
    for t in data.get("types", []):
        found = _find(session, ItemType, t["name"])
        new = found is None
        if new:
            report["types"].append(t["name"])
            if apply:
                found = api.create_type(
                    session,
                    actor,
                    {
                        **{
                            k: t.get(k)
                            for k in (
                                "name",
                                "width",
                                "depth",
                                "height",
                                "mount",
                                "mount_height",
                                "top_view",
                                "icon",
                                "price",
                                "accounting",
                                "unit",
                                "life_months",
                                "container",
                            )
                            if t.get(k) is not None
                        },
                        "layer_id": layers.get(t["layer"]) if t.get("layer") else None,
                        "set_ids": [sets[s] for s in t.get("sets", []) if sets.get(s)],
                    },
                )
                for c in t.get("characteristics", []):
                    api.create_characteristic(session, actor, {**c, "type_id": found.id})
                m3 = t.get("model3d")
                if m3 and files.get(m3["file"]):
                    api.attach_model3d(
                        session,
                        actor,
                        found.id,
                        files[m3["file"]],
                        m3.get("size"),
                        m3.get("credit", ""),
                        m3.get("transform"),
                    )
                if t.get("values"):
                    _set_named(session, actor, found, None, t["values"])
        maps["types"][t["key"]] = found.id if found else None
        # характеристики «у каждой вещи»: по названию; нет у найденного типа — добавить
        if found is not None:
            have = {c.name.lower(): c for c in api.characteristics_of(session, found)}
            for key, name in t.get("item_chars", {}).items():
                ch = have.get(name.lower())
                if ch is None and not new:
                    report["characteristics"].append(f"{found.name}: {name}")
                    src = (
                        next((c for c in t.get("characteristics", []) if c["name"] == name), None)
                        or _set_char(data, t, name)
                        or {"name": name, "kind": "text"}
                    )
                    if apply:
                        ch = api.create_characteristic(
                            session, actor, {**src, "level": "item", "type_id": found.id}
                        )
                if ch is not None:
                    maps["item_chars"][(t["key"], key)] = str(ch.id)
    for m in data.get("models", []):
        type_id = maps["types"].get(m["type"])
        found = None
        if type_id:
            found = session.scalar(
                select(Model).where(
                    Model.type_id == type_id,
                    func.lower(Model.name) == m["name"].lower(),
                    func.lower(Model.manufacturer) == (m.get("manufacturer") or "").lower(),
                )
            )
        if found is None:
            report["models"].append(f"{m.get('manufacturer', '')} {m['name']}".strip())
            if apply and type_id:
                found = api.create_model(
                    session,
                    actor,
                    type_id,
                    {k: m.get(k) for k in ("manufacturer", "name", "article", "supplier", "price")},
                )
                if m.get("values"):
                    _set_named(session, actor, api.get_type(session, type_id), found, m["values"])
        maps["models"][m["key"]] = found.id if found else None
    return {"report": report, "maps": maps}


def _set_char(data: dict[str, Any], t: dict[str, Any], name: str) -> dict[str, Any] | None:
    for s in data.get("sets", []):
        if s["name"] in t.get("sets", []):
            for c in s.get("characteristics", []):
                if c["name"] == name:
                    return dict(c)
    return None


def _set_named(
    session: Session, actor: Actor, t: ItemType, model: Model | None, values: dict[str, Any]
) -> None:
    level = "model" if model else "type"
    chars = {c.name.lower(): c for c in api.characteristics_of(session, t) if c.level == level}
    raw = {str(chars[n.lower()].id): v for n, v in values.items() if n.lower() in chars}
    if raw:
        api.set_values(session, actor, raw, item_type=t, model=model)
