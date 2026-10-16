"""Программный интерфейс каталога (5.2) для других модулей и маршрутов.

Слои, наборы, характеристики, типы, модели и назначения помещений — данные: добавляются
администратором без доработки системы (1.5). Цены «просмотру» не отдаются (2.2)."""

import re
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound, stale
from app.modules.catalog.models import (
    Characteristic,
    CharSet,
    ItemType,
    Layer,
    Model,
    Purpose,
    TypeSet,
    Value,
)
from app.modules.journal import api as journal

MOUNTS = {"floor": "на пол", "wall": "на стену", "ceiling": "на потолок", "none": "не ставится"}
KINDS = {"text": "текст", "number": "число", "date": "дата", "bool": "да/нет", "choice": "выбор"}
LEVELS = {"type": "тип", "model": "модель", "item": "вещь"}
ACCOUNTING = {"piece": "поштучно", "quantity": "количеством"}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden()


def _name(value: str | None, what: str = "название", limit: int = 200) -> str:
    value = (value or "").strip()
    if not value:
        raise AppError(f"Укажите {what}.", field="name", code="required")
    if len(value) > limit:
        raise AppError(f"Не длиннее {limit} знаков.", field="name")
    return value


def _get(session: Session, cls: type, obj_id: uuid.UUID, what: str):  # type: ignore[no-untyped-def]
    obj = session.get(cls, obj_id)
    if obj is None:
        raise NotFound(f"{what} не найден{'а' if what.endswith('а') else ''}.")
    return obj


def _check_version(obj: Any, version: int | None, what: str) -> None:
    if version is not None and obj.version != version:
        raise stale(what)


def _record(
    session: Session,
    actor: Actor | None,
    action: str,
    summary: str,
    entity: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    journal.record(
        session, actor, action, summary, entity=entity, refs=["catalog"], before=before, after=after
    )


def _apply(
    obj: Any, values: dict[str, Any], fields: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    before = {f: getattr(obj, f) for f in fields if f in values}
    for f in fields:
        if f in values:
            setattr(obj, f, values[f])
    after = {f: getattr(obj, f) for f in fields if f in values}
    return journal.changes(before, after)


# ---------------------------------------------------------------- значения характеристик


def parse_value(ch: Characteristic, raw: Any) -> Any:
    """Значение по виду характеристики; пустое — None."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if ch.kind == "number":
        try:
            return float(str(raw).replace(",", ".").replace(" ", "").replace(" ", ""))
        except ValueError:
            raise AppError(f"«{ch.name}» — число, а не «{raw}».", field=str(ch.id)) from None
    if ch.kind == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("да", "yes", "true", "1", "+"):
            return True
        if text in ("нет", "no", "false", "0", "-"):
            return False
        raise AppError(f"«{ch.name}» — да или нет.", field=str(ch.id))
    if ch.kind == "date":
        if isinstance(raw, datetime | date):
            return (raw.date() if isinstance(raw, datetime) else raw).isoformat()
        text = str(raw).strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        raise AppError(f"«{ch.name}» — дата, например 16.10.2026.", field=str(ch.id))
    if ch.kind == "choice":
        text = str(raw).strip()
        match = next((c for c in ch.choices if c.lower() == text.lower()), None)
        if match is None:
            raise AppError(
                f"«{ch.name}»: «{text}» нет в списке ({', '.join(ch.choices)}).", field=str(ch.id)
            )
        return match
    return str(raw).strip()[:1000]


def format_value(ch: Characteristic, value: Any) -> str:
    if value is None:
        return ""
    if ch.kind == "bool":
        return "да" if value else "нет"
    if ch.kind == "number":
        text = f"{value:g}".replace(".", ",")
        return text
    if ch.kind == "date":
        try:
            return date.fromisoformat(value).strftime("%d.%m.%Y")
        except ValueError:
            return str(value)
    return str(value)


def characteristics_of(session: Session, item_type: ItemType) -> list[Characteristic]:
    """Характеристики типа: из его наборов, затем свои."""
    set_ids = [
        r for r in session.scalars(select(TypeSet.set_id).where(TypeSet.type_id == item_type.id))
    ]
    sets = sorted((session.get(CharSet, s) for s in set_ids), key=lambda s: (s.position, s.name))
    out = [c for s in sets if s for c in s.characteristics]
    out += list(
        session.scalars(
            select(Characteristic)
            .where(Characteristic.type_id == item_type.id)
            .order_by(Characteristic.position)
        )
    )
    return out


def _values(
    session: Session, *, type_id: uuid.UUID | None = None, model_id: uuid.UUID | None = None
) -> dict[uuid.UUID, Any]:
    q = select(Value.characteristic_id, Value.value)
    q = q.where(Value.type_id == type_id) if type_id else q.where(Value.model_id == model_id)
    return dict(session.execute(q).all())  # type: ignore[arg-type]


def values_of(
    session: Session, *, type_id: uuid.UUID | None = None, model_id: uuid.UUID | None = None
) -> dict[uuid.UUID, Any]:
    """Значения характеристик уровня типа или модели — для модулей выше."""
    return _values(session, type_id=type_id, model_id=model_id)


def set_values(
    session: Session,
    actor: Actor | None,
    values: dict[str, Any],
    *,
    item_type: ItemType,
    model: Model | None = None,
) -> None:
    """Значения уровня типа (model=None) или модели. Пустое значение — удалить."""
    chars = {str(c.id): c for c in characteristics_of(session, item_type)}
    level = "model" if model else "type"
    current = (
        _values(session, model_id=model.id) if model else _values(session, type_id=item_type.id)
    )
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for key, raw in values.items():
        ch = chars.get(str(key))
        if ch is None:
            raise AppError("Такой характеристики у типа нет — обновите страницу.", field=str(key))
        if ch.level != level:
            raise AppError(
                f"«{ch.name}» задаётся у {LEVELS[ch.level]}а, а не здесь.", field=str(key)
            )
        value = parse_value(ch, raw)
        old = current.get(ch.id)
        if old == value:
            continue
        session.execute(
            delete(Value).where(
                Value.characteristic_id == ch.id,
                Value.model_id == model.id if model else Value.type_id == item_type.id,
            )
        )
        if value is not None:
            session.add(
                Value(
                    characteristic_id=ch.id,
                    type_id=None if model else item_type.id,
                    model_id=model.id if model else None,
                    value=value,
                )
            )
        before[ch.name] = format_value(ch, old)
        after[ch.name] = format_value(ch, value)
    if after:
        session.flush()
        title = f"модели «{model.name}»" if model else f"типа «{item_type.name}»"
        _record(
            session,
            actor,
            "catalog.values",
            f"Изменены характеристики {title}",
            f"{'model' if model else 'type'}:{(model or item_type).id}",
            before,
            after,
        )


# ---------------------------------------------------------------- кто использует тип

# модули выше (расстановка, учёт) сообщают, сколько у них ссылок на тип или модель
_usage: list[Callable[[Session, uuid.UUID | None, uuid.UUID | None], int]] = []


def on_usage(check: Callable[[Session, uuid.UUID | None, uuid.UUID | None], int]) -> None:
    _usage.append(check)


def used(
    session: Session, type_id: uuid.UUID | None = None, model_id: uuid.UUID | None = None
) -> int:
    return sum(check(session, type_id, model_id) for check in _usage)


# ---------------------------------------------------------------- слои (5.2.1)


def layer_view(layer: Layer, types: int = 0) -> dict[str, Any]:
    return {
        "id": layer.id,
        "name": layer.name,
        "color": layer.color,
        "icon": layer.icon,
        "note": layer.note,
        "position": layer.position,
        "visible": layer.visible,
        "types": types,
        "version": layer.version,
    }


def _layer_values(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    if "name" in out:
        out["name"] = _name(out["name"], limit=100)
    if "color" in out and not HEX.match(str(out["color"])):
        raise AppError("Цвет — в виде #RRGGBB.", field="color")
    return out


def _unique(
    session: Session, cls: type, name: str, exclude: uuid.UUID | None, what: str, **where: Any
) -> None:
    q = select(cls.id).where(func.lower(cls.name) == name.lower())  # type: ignore[attr-defined]
    for k, v in where.items():
        q = q.where(getattr(cls, k) == v)
    if exclude:
        q = q.where(cls.id != exclude)  # type: ignore[attr-defined]
    if hasattr(cls, "archived_at"):
        q = q.where(cls.archived_at.is_(None))  # type: ignore[attr-defined]
    if session.scalar(q):
        raise Conflict(f"{what} «{name}» уже есть.", field="name", code="duplicate")


def create_layer(session: Session, actor: Actor, values: dict[str, Any]) -> Layer:
    _admin(actor)
    v = _layer_values(values)
    _unique(session, Layer, v["name"], None, "Слой")
    position = v.get("position") or (session.scalar(select(func.max(Layer.position))) or 0) + 1
    layer = Layer(
        id=uuid.uuid4(),
        name=v["name"],
        color=v.get("color", "#607D8B"),
        icon=v.get("icon", ""),
        note=v.get("note", ""),
        position=position,
        visible=v.get("visible", True),
        version=1,
    )
    session.add(layer)
    session.flush()
    _record(
        session,
        actor,
        "catalog.layer_create",
        f"Добавлен слой «{layer.name}»",
        f"layer:{layer.id}",
        after={"name": layer.name, "color": layer.color},
    )
    return layer


def update_layer(
    session: Session, actor: Actor, layer_id: uuid.UUID, values: dict[str, Any]
) -> Layer:
    _admin(actor)
    layer = _get(session, Layer, layer_id, "Слой")
    _check_version(layer, values.pop("version", None), "Слой")
    v = _layer_values(values)
    if "name" in v:
        _unique(session, Layer, v["name"], layer.id, "Слой")
    was, became = _apply(layer, v, ["name", "color", "icon", "note", "position", "visible"])
    if became:
        layer.version += 1
        _record(
            session,
            actor,
            "catalog.layer_update",
            f"Изменён слой «{layer.name}»",
            f"layer:{layer.id}",
            was,
            became,
        )
    return layer


def delete_layer(session: Session, actor: Actor, layer_id: uuid.UUID) -> None:
    _admin(actor)
    layer = _get(session, Layer, layer_id, "Слой")
    if session.scalar(
        select(func.count()).select_from(ItemType).where(ItemType.layer_id == layer.id)
    ):
        raise Conflict("В слое есть типы — удалить его нельзя, можно скрыть.", code="layer_in_use")
    session.delete(layer)
    _record(
        session,
        actor,
        "catalog.layer_delete",
        f"Удалён слой «{layer.name}»",
        f"layer:{layer.id}",
        before={"name": layer.name},
    )


# ---------------------------------------------------------------- наборы и характеристики


def char_view(ch: Characteristic) -> dict[str, Any]:
    return {
        "id": ch.id,
        "set_id": ch.set_id,
        "type_id": ch.type_id,
        "name": ch.name,
        "kind": ch.kind,
        "unit": ch.unit,
        "choices": ch.choices,
        "level": ch.level,
        "required": ch.required,
        "note": ch.note,
        "position": ch.position,
        "version": ch.version,
    }


def set_view(s: CharSet, types: int = 0) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "position": s.position,
        "types": types,
        "characteristics": [char_view(c) for c in s.characteristics],
        "version": s.version,
    }


def create_set(session: Session, actor: Actor, name: str) -> CharSet:
    _admin(actor)
    name = _name(name, limit=100)
    _unique(session, CharSet, name, None, "Набор")
    s = CharSet(
        id=uuid.uuid4(),
        name=name,
        version=1,
        position=(session.scalar(select(func.max(CharSet.position))) or 0) + 1,
    )
    session.add(s)
    session.flush()
    _record(
        session,
        actor,
        "catalog.set_create",
        f"Добавлен набор характеристик «{name}»",
        f"set:{s.id}",
    )
    return s


def update_set(
    session: Session, actor: Actor, set_id: uuid.UUID, name: str, version: int
) -> CharSet:
    _admin(actor)
    s = _get(session, CharSet, set_id, "Набор")
    _check_version(s, version, "Набор")
    name = _name(name, limit=100)
    _unique(session, CharSet, name, s.id, "Набор")
    if name != s.name:
        old, s.name = s.name, name
        s.version += 1
        _record(
            session,
            actor,
            "catalog.set_update",
            f"Набор «{old}» переименован в «{name}»",
            f"set:{s.id}",
            {"name": old},
            {"name": name},
        )
    return s


def delete_set(session: Session, actor: Actor, set_id: uuid.UUID) -> None:
    _admin(actor)
    s = _get(session, CharSet, set_id, "Набор")
    if session.scalar(select(func.count()).select_from(TypeSet).where(TypeSet.set_id == s.id)):
        raise Conflict("Набор входит в типы — сначала уберите его из них.", code="set_in_use")
    session.delete(s)
    _record(
        session,
        actor,
        "catalog.set_delete",
        f"Удалён набор характеристик «{s.name}»",
        f"set:{s.id}",
    )


def _char_values(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    if "name" in out:
        out["name"] = _name(out["name"], limit=150)
    if "kind" in out and out["kind"] not in KINDS:
        raise AppError("Вид значения — текст, число, дата, да/нет или выбор.", field="kind")
    if "level" in out and out["level"] not in LEVELS:
        raise AppError("Уровень — тип, модель или вещь.", field="level")
    if "choices" in out:
        out["choices"] = [str(c).strip() for c in out["choices"] or [] if str(c).strip()]
    if out.get("kind") == "choice" and not out.get("choices"):
        raise AppError("Для выбора из списка перечислите варианты.", field="choices")
    return out


def create_characteristic(session: Session, actor: Actor, values: dict[str, Any]) -> Characteristic:
    _admin(actor)
    v = _char_values(values)
    set_id, type_id = v.get("set_id"), v.get("type_id")
    if bool(set_id) == bool(type_id):
        raise AppError("Характеристика — либо в наборе, либо своя у типа.")
    owner = (
        _get(session, CharSet, set_id, "Набор")
        if set_id
        else _get(session, ItemType, type_id, "Тип")
    )
    q = select(Characteristic.id).where(func.lower(Characteristic.name) == v["name"].lower())
    q = (
        q.where(Characteristic.set_id == set_id)
        if set_id
        else q.where(Characteristic.type_id == type_id)
    )
    if session.scalar(q):
        raise Conflict(f"Характеристика «{v['name']}» здесь уже есть.", field="name")
    position = (
        session.scalar(
            select(func.max(Characteristic.position)).where(
                Characteristic.set_id == set_id if set_id else Characteristic.type_id == type_id
            )
        )
        or 0
    )
    ch = Characteristic(
        id=uuid.uuid4(),
        set_id=set_id,
        type_id=type_id,
        name=v["name"],
        kind=v.get("kind", "text"),
        unit=v.get("unit", "") or "",
        choices=v.get("choices", []),
        level=v.get("level", "type"),
        required=bool(v.get("required")),
        note=v.get("note", "") or "",
        position=position + 1,
        version=1,
    )
    session.add(ch)
    session.flush()
    where = f"набор «{owner.name}»" if set_id else f"тип «{owner.name}»"
    _record(
        session,
        actor,
        "catalog.char_create",
        f"Добавлена характеристика «{ch.name}» в {where}",
        f"characteristic:{ch.id}",
        after={"вид": KINDS[ch.kind], "уровень": LEVELS[ch.level]},
    )
    return ch


def update_characteristic(
    session: Session, actor: Actor, char_id: uuid.UUID, values: dict[str, Any]
) -> Characteristic:
    _admin(actor)
    ch = _get(session, Characteristic, char_id, "Характеристика")
    _check_version(ch, values.pop("version", None), "Характеристику")
    v = _char_values(
        {
            **values,
            **({} if "kind" in values else {"kind": ch.kind}),
            **({} if "choices" in values else {"choices": ch.choices}),
        }
    )
    if ("kind" in values and values["kind"] != ch.kind) or (
        "level" in values and values["level"] != ch.level
    ):
        # вид или уровень сменились — прежние значения больше не подходят
        session.execute(delete(Value).where(Value.characteristic_id == ch.id))
    was, became = _apply(
        ch, v, ["name", "kind", "unit", "choices", "level", "required", "note", "position"]
    )
    if became:
        ch.version += 1
        _record(
            session,
            actor,
            "catalog.char_update",
            f"Изменена характеристика «{ch.name}»",
            f"characteristic:{ch.id}",
            was,
            became,
        )
    return ch


def delete_characteristic(session: Session, actor: Actor, char_id: uuid.UUID) -> None:
    _admin(actor)
    ch = _get(session, Characteristic, char_id, "Характеристика")
    session.delete(ch)
    _record(
        session,
        actor,
        "catalog.char_delete",
        f"Удалена характеристика «{ch.name}»",
        f"characteristic:{ch.id}",
    )


# ---------------------------------------------------------------- типы (5.2.2)

TYPE_FIELDS = [
    "name",
    "layer_id",
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
    "model_transform",
]


def _price(actor: Actor, value: Any) -> Any:
    return (float(value) if value is not None else None) if actor.sees_cost else None


def type_brief(t: ItemType, actor: Actor) -> dict[str, Any]:
    out = {
        "id": t.id,
        "name": t.name,
        "layer_id": t.layer_id,
        "mount": t.mount,
        "width": t.width,
        "depth": t.depth,
        "height": t.height,
        "mount_height": t.mount_height,
        "accounting": t.accounting,
        "unit": t.unit,
        "container": t.container,
        "top_view": t.top_view,
        "icon": t.icon,
        "model_url": f"/api/files/{t.model_file_id}" if t.model_file_id else None,
        "model_transform": t.model_transform or {},
        "model_size": t.model_size,
        "model_credit": t.model_credit or None,
        "archived": t.archived_at is not None,
        "version": t.version,
    }
    if actor.sees_cost:
        out["price"] = _price(actor, t.price)
    return out


def model_view(
    session: Session, m: Model, chars: list[Characteristic], actor: Actor
) -> dict[str, Any]:
    values = _values(session, model_id=m.id)
    out = {
        "id": m.id,
        "type_id": m.type_id,
        "manufacturer": m.manufacturer,
        "name": m.name,
        "article": m.article,
        "supplier": m.supplier,
        "archived": m.archived_at is not None,
        "version": m.version,
        "values": {str(c.id): values.get(c.id) for c in chars if c.level == "model"},
    }
    if actor.sees_cost:
        out["price"] = _price(actor, m.price)
    return out


def type_view(session: Session, t: ItemType, actor: Actor) -> dict[str, Any]:
    chars = characteristics_of(session, t)
    values = _values(session, type_id=t.id)
    set_ids = [
        str(s) for s in session.scalars(select(TypeSet.set_id).where(TypeSet.type_id == t.id))
    ]
    models = list(
        session.scalars(
            select(Model)
            .where(Model.type_id == t.id)
            .order_by(Model.archived_at.is_not(None), Model.manufacturer, Model.name)
        )
    )
    return {
        **type_brief(t, actor),
        "set_ids": set_ids,
        "characteristics": [char_view(c) for c in chars],
        "values": {str(c.id): values.get(c.id) for c in chars if c.level == "type"},
        "models": [model_view(session, m, chars, actor) for m in models],
        "life_months": t.life_months,
        "used": used(session, type_id=t.id),
    }


def _type_values(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    if "name" in out:
        out["name"] = _name(out["name"])
    if out.get("layer_id"):
        _get(session, Layer, out["layer_id"], "Слой")
    if "mount" in out and out["mount"] not in MOUNTS:
        raise AppError("Установка — на пол, на стену, на потолок или не ставится.", field="mount")
    if "accounting" in out and out["accounting"] not in ACCOUNTING:
        raise AppError("Учёт — поштучно или количеством.", field="accounting")
    for key in ("width", "depth", "height", "mount_height"):
        if out.get(key) is not None and not 0 < float(out[key]) <= 100_000:
            raise AppError("Размер — от 1 до 100 000 мм.", field=key)
    if out.get("price") is not None and float(out["price"]) < 0:
        raise AppError("Цена не может быть отрицательной.", field="price")
    if out.get("life_months") is not None and not 1 <= int(out["life_months"]) <= 1200:
        raise AppError("Срок службы — от 1 до 1200 месяцев.", field="life_months")
    if "model_transform" in out:
        tr = out["model_transform"] or {}
        out["model_transform"] = {
            **{k: float(tr.get(k, 0)) % 360 for k in ("rx", "ry", "rz")},
            "scale": float(tr.get("scale", 1)) if 0 < float(tr.get("scale", 1)) <= 1000 else 1.0,
            # вписать модель в габариты типа по каждой оси
            "fit": bool(tr.get("fit", False)),
        }
    if "top_view" in out and out["top_view"] not in ("box", "icon"):
        raise AppError("Вид сверху — контур или значок.", field="top_view")
    return out


def is_model_file(session: Session, _actor: Actor, file_id: uuid.UUID) -> bool:
    q = select(ItemType.id).where(ItemType.model_file_id == file_id).limit(1)
    return session.scalar(q) is not None


def types_by_id(session: Session, ids: Any) -> dict[uuid.UUID, ItemType]:
    """Типы по ключам — для модулей выше (учёт, планировка)."""
    ids = list(set(ids))
    if not ids:
        return {}
    return {t.id: t for t in session.scalars(select(ItemType).where(ItemType.id.in_(ids)))}


def models_by_id(session: Session, ids: Any) -> dict[uuid.UUID, Model]:
    ids = [i for i in set(ids) if i]
    if not ids:
        return {}
    return {m.id: m for m in session.scalars(select(Model).where(Model.id.in_(ids)))}


def type_ids(
    session: Session, layer_id: uuid.UUID | None = None, text: str | None = None
) -> list[uuid.UUID]:
    q = select(ItemType.id)
    if layer_id is not None:
        q = q.where(ItemType.layer_id == layer_id)
    if text:
        q = q.where(ItemType.name.ilike(f"%{text}%"))
    return list(session.scalars(q))


def named_values(
    session: Session, item_type: ItemType, model_id: uuid.UUID | None
) -> dict[str, Any]:
    """Значения характеристик типа и модели по названию характеристики (для расчётов, 5.2.5)."""
    names = {c.id: c.name for c in characteristics_of(session, item_type)}
    out = {names[k]: v for k, v in _values(session, type_id=item_type.id).items() if k in names}
    if model_id is not None:
        out.update(
            {names[k]: v for k, v in _values(session, model_id=model_id).items() if k in names}
        )
    return out


def types_with(session: Session, names: list[str]) -> list[ItemType]:
    """Типы, у которых есть все эти характеристики (из наборов или свои)."""
    wanted = set(names)
    found: dict[uuid.UUID, set[str]] = {}
    from_sets = select(TypeSet.type_id, Characteristic.name).join(
        Characteristic, Characteristic.set_id == TypeSet.set_id
    )
    own = select(Characteristic.type_id, Characteristic.name).where(
        Characteristic.type_id.is_not(None)
    )
    for q in (from_sets, own):
        for type_id, name in session.execute(q.where(Characteristic.name.in_(wanted))):
            found.setdefault(type_id, set()).add(name)
    ids = [t for t, have in found.items() if wanted <= have]
    return sorted(types_by_id(session, ids).values(), key=lambda t: t.name)


def purpose_map(session: Session) -> dict[str, Purpose]:
    """Назначения помещений по ключу (строкой, как в плане)."""
    return {str(p.id): p for p in purposes(session, archived=True)}


def models_of(session: Session, type_id: uuid.UUID) -> list[Model]:
    return list(session.scalars(select(Model).where(Model.type_id == type_id)))


def all_types(session: Session) -> list[ItemType]:
    return list(session.scalars(select(ItemType).order_by(ItemType.name)))


def layer_colors(session: Session) -> dict[uuid.UUID, str]:
    return dict(session.execute(select(Layer.id, Layer.color)).all())  # type: ignore[arg-type]


def layer_names(session: Session) -> dict[uuid.UUID, str]:
    return dict(session.execute(select(Layer.id, Layer.name)).all())  # type: ignore[arg-type]


def get_type(session: Session, type_id: uuid.UUID) -> ItemType:
    return _get(session, ItemType, type_id, "Тип")


def create_type(session: Session, actor: Actor, values: dict[str, Any]) -> ItemType:
    _admin(actor)
    v = _type_values(session, values)
    _unique(session, ItemType, v["name"], None, "Тип")
    t = ItemType(id=uuid.uuid4(), version=1, model_transform={})
    for f in TYPE_FIELDS:
        if f in v:
            setattr(t, f, v[f])
    t.mount = t.mount or ("floor" if t.layer_id else "none")
    t.accounting = t.accounting or "piece"
    t.unit = t.unit or "шт."
    session.add(t)
    session.flush()
    _set_sets(session, t, values.get("set_ids") or [])
    _record(
        session,
        actor,
        "catalog.type_create",
        f"Добавлен тип «{t.name}»",
        f"type:{t.id}",
        after={
            "слой": _layer_name(session, t.layer_id),
            "установка": MOUNTS[t.mount],
            "учёт": ACCOUNTING[t.accounting],
        },
    )
    return t


def _layer_name(session: Session, layer_id: uuid.UUID | None) -> str:
    layer = session.get(Layer, layer_id) if layer_id else None
    return layer.name if layer else "без слоя"


def _set_sets(session: Session, t: ItemType, set_ids: list[Any]) -> list[str]:
    wanted = {uuid.UUID(str(s)) for s in set_ids}
    for s in wanted:
        _get(session, CharSet, s, "Набор")
    have = set(session.scalars(select(TypeSet.set_id).where(TypeSet.type_id == t.id)))
    for s in wanted - have:
        session.add(TypeSet(type_id=t.id, set_id=s))
    if have - wanted:
        session.execute(
            delete(TypeSet).where(TypeSet.type_id == t.id, TypeSet.set_id.in_(have - wanted))
        )
    session.flush()
    return sorted(session.get(CharSet, s).name for s in wanted)  # type: ignore[union-attr]


def update_type(
    session: Session, actor: Actor, type_id: uuid.UUID, values: dict[str, Any]
) -> ItemType:
    _admin(actor)
    t = get_type(session, type_id)
    _check_version(t, values.pop("version", None), "Тип")
    set_ids = values.pop("set_ids", None)
    v = _type_values(session, values)
    if "name" in v:
        _unique(session, ItemType, v["name"], t.id, "Тип")
    was, became = _apply(t, v, TYPE_FIELDS)
    if set_ids is not None:
        before_sets = sorted(
            session.get(CharSet, s).name
            for s in session.scalars(  # type: ignore[union-attr]
                select(TypeSet.set_id).where(TypeSet.type_id == t.id)
            )
        )
        after_sets = _set_sets(session, t, set_ids)
        if before_sets != after_sets:
            was["наборы"], became["наборы"] = before_sets, after_sets
    if became:
        t.version += 1
        for key in ("layer_id",):
            if key in became:
                was[key] = _layer_name(session, was[key])
                became[key] = _layer_name(session, became[key])
        _record(
            session,
            actor,
            "catalog.type_update",
            f"Изменён тип «{t.name}»",
            f"type:{t.id}",
            was,
            became,
        )
    return t


def set_archived_type(
    session: Session, actor: Actor, type_id: uuid.UUID, archived: bool
) -> ItemType:
    _admin(actor)
    t = get_type(session, type_id)
    if (t.archived_at is not None) == archived:
        return t
    if not archived:
        _unique(session, ItemType, t.name, t.id, "Тип")
    t.archived_at = datetime.now(UTC) if archived else None
    t.version += 1
    _record(
        session,
        actor,
        "catalog.type_archive" if archived else "catalog.type_unarchive",
        f"Тип «{t.name}» {'отправлен в архив' if archived else 'возвращён из архива'}",
        f"type:{t.id}",
    )
    return t


def delete_type(session: Session, actor: Actor, type_id: uuid.UUID) -> None:
    _admin(actor)
    t = get_type(session, type_id)
    if used(session, type_id=t.id):
        raise Conflict(
            "Тип используется — удалить его нельзя, можно отправить в архив.", code="type_in_use"
        )
    session.delete(t)
    _record(session, actor, "catalog.type_delete", f"Удалён тип «{t.name}»", f"type:{t.id}")


def attach_model3d(
    session: Session,
    actor: Actor,
    type_id: uuid.UUID,
    file_id: uuid.UUID | None,
    size: list[float] | None,
    credit: str = "",
    transform: dict[str, Any] | None = None,
) -> ItemType:
    _admin(actor)
    t = get_type(session, type_id)
    old = t.model_file_id
    t.model_file_id = file_id
    t.model_size = size
    t.model_credit = credit
    t.model_transform = (transform or {"rx": 0, "ry": 0, "rz": 0, "scale": 1}) if file_id else {}
    t.version += 1
    _record(
        session,
        actor,
        "catalog.type_model3d",
        f"{'Загружена' if file_id else 'Убрана'} 3D-модель типа «{t.name}»",
        f"type:{t.id}",
        {"3D-модель": "есть" if old else "нет"},
        {"3D-модель": "есть" if file_id else "нет"},
    )
    return t


# ---------------------------------------------------------------- модели (5.2.3)

MODEL_FIELDS = ["manufacturer", "name", "article", "supplier", "price"]


def _model_values(values: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in values.items() if k in MODEL_FIELDS}
    if "name" in out:
        out["name"] = _name(out["name"], "название модели")
    for k in ("manufacturer", "article", "supplier"):
        if k in out:
            out[k] = (out[k] or "").strip()
    if out.get("price") is not None and float(out["price"]) < 0:
        raise AppError("Цена не может быть отрицательной.", field="price")
    return out


def create_model(
    session: Session, actor: Actor, type_id: uuid.UUID, values: dict[str, Any]
) -> Model:
    _admin(actor)
    t = get_type(session, type_id)
    v = _model_values(values)
    _unique_model(session, t.id, v.get("manufacturer", ""), v["name"], None)
    m = Model(id=uuid.uuid4(), type_id=t.id, version=1, manufacturer="", article="", supplier="")
    for f in MODEL_FIELDS:
        if f in v:
            setattr(m, f, v[f])
    session.add(m)
    session.flush()
    _record(
        session,
        actor,
        "catalog.model_create",
        f"Добавлена модель «{m.manufacturer} {m.name}» типа «{t.name}»".replace("« ", "«"),
        f"model:{m.id}",
    )
    return m


def _unique_model(
    session: Session, type_id: uuid.UUID, manufacturer: str, name: str, exclude: uuid.UUID | None
) -> None:
    q = select(Model.id).where(
        Model.type_id == type_id,
        Model.archived_at.is_(None),
        func.lower(Model.name) == name.lower(),
        func.lower(Model.manufacturer) == manufacturer.lower(),
    )
    if exclude:
        q = q.where(Model.id != exclude)
    if session.scalar(q):
        raise Conflict(
            f"Модель «{manufacturer} {name}» у этого типа уже есть.".replace("« ", "«"),
            field="name",
            code="duplicate",
        )


def get_model(session: Session, model_id: uuid.UUID) -> Model:
    return _get(session, Model, model_id, "Модель")


def update_model(
    session: Session, actor: Actor, model_id: uuid.UUID, values: dict[str, Any]
) -> Model:
    _admin(actor)
    m = get_model(session, model_id)
    _check_version(m, values.pop("version", None), "Модель")
    v = _model_values(values)
    if "name" in v or "manufacturer" in v:
        _unique_model(
            session, m.type_id, v.get("manufacturer", m.manufacturer), v.get("name", m.name), m.id
        )
    was, became = _apply(m, v, MODEL_FIELDS)
    if became:
        m.version += 1
        _record(
            session,
            actor,
            "catalog.model_update",
            f"Изменена модель «{m.name}»",
            f"model:{m.id}",
            {k: str(x) for k, x in was.items()},
            {k: str(x) for k, x in became.items()},
        )
    return m


def set_archived_model(
    session: Session, actor: Actor, model_id: uuid.UUID, archived: bool
) -> Model:
    _admin(actor)
    m = get_model(session, model_id)
    if (m.archived_at is not None) != archived:
        m.archived_at = datetime.now(UTC) if archived else None
        m.version += 1
        _record(
            session,
            actor,
            "catalog.model_archive",
            f"Модель «{m.name}» {'в архиве' if archived else 'возвращена из архива'}",
            f"model:{m.id}",
        )
    return m


def delete_model(session: Session, actor: Actor, model_id: uuid.UUID) -> None:
    _admin(actor)
    m = get_model(session, model_id)
    if used(session, model_id=m.id):
        raise Conflict(
            "Модель используется — удалить её нельзя, можно отправить в архив.", code="model_in_use"
        )
    session.delete(m)
    _record(session, actor, "catalog.model_delete", f"Удалена модель «{m.name}»", f"model:{m.id}")


# ---------------------------------------------------------------- назначения помещений


def purpose_view(p: Purpose) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "surface": p.surface,
        "norm": p.norm,
        "note": p.note,
        "position": p.position,
        "archived": p.archived_at is not None,
        "version": p.version,
    }


def _purpose_values(values: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in values.items() if k in ("name", "surface", "norm", "note", "position")}
    if "name" in out:
        out["name"] = _name(out["name"], limit=150)
    if "surface" in out and not 0 <= float(out["surface"]) <= 3000:
        raise AppError("Высота рабочей поверхности — от 0 до 3000 мм.", field="surface")
    if "norm" in out and not 0 < int(out["norm"]) <= 10000:
        raise AppError("Норма — от 1 до 10 000 лк.", field="norm")
    return out


def purposes(session: Session, archived: bool = False) -> list[Purpose]:
    q = select(Purpose).order_by(Purpose.position, Purpose.name)
    if not archived:
        q = q.where(Purpose.archived_at.is_(None))
    return list(session.scalars(q))


def create_purpose(session: Session, actor: Actor, values: dict[str, Any]) -> Purpose:
    _admin(actor)
    v = _purpose_values(values)
    _unique(session, Purpose, v["name"], None, "Назначение")
    p = Purpose(
        id=uuid.uuid4(),
        name=v["name"],
        surface=v.get("surface", 800),
        norm=v.get("norm", 300),
        note=v.get("note", "") or "",
        version=1,
        position=(session.scalar(select(func.max(Purpose.position))) or 0) + 1,
    )
    session.add(p)
    session.flush()
    _record(
        session,
        actor,
        "catalog.purpose_create",
        f"Добавлено назначение «{p.name}»",
        f"purpose:{p.id}",
        after={"норма, лк": p.norm, "поверхность, мм": p.surface},
    )
    return p


def update_purpose(
    session: Session, actor: Actor, purpose_id: uuid.UUID, values: dict[str, Any]
) -> Purpose:
    _admin(actor)
    p = _get(session, Purpose, purpose_id, "Назначение")
    _check_version(p, values.pop("version", None), "Назначение")
    v = _purpose_values(values)
    if "name" in v:
        _unique(session, Purpose, v["name"], p.id, "Назначение")
    was, became = _apply(p, v, ["name", "surface", "norm", "note", "position"])
    if became:
        p.version += 1
        _record(
            session,
            actor,
            "catalog.purpose_update",
            f"Изменено назначение «{p.name}»",
            f"purpose:{p.id}",
            was,
            became,
        )
    return p


def set_archived_purpose(
    session: Session, actor: Actor, purpose_id: uuid.UUID, archived: bool
) -> Purpose:
    _admin(actor)
    p = _get(session, Purpose, purpose_id, "Назначение")
    if (p.archived_at is not None) != archived:
        p.archived_at = datetime.now(UTC) if archived else None
        p.version += 1
        _record(
            session,
            actor,
            "catalog.purpose_archive",
            f"Назначение «{p.name}» {'в архиве' if archived else 'возвращено'}",
            f"purpose:{p.id}",
        )
    return p


# ---------------------------------------------------------------- всё дерево каталога


def tree(session: Session, actor: Actor, archived: bool = False) -> dict[str, Any]:
    counts = dict(
        session.execute(
            select(ItemType.layer_id, func.count())
            .where(ItemType.archived_at.is_(None))
            .group_by(ItemType.layer_id)
        ).all()
    )  # type: ignore[arg-type]
    set_counts = dict(
        session.execute(select(TypeSet.set_id, func.count()).group_by(TypeSet.set_id)).all()
    )  # type: ignore[arg-type]
    types = select(ItemType).order_by(ItemType.name)
    if not archived:
        types = types.where(ItemType.archived_at.is_(None))
    return {
        "layers": [
            layer_view(x, counts.get(x.id, 0))
            for x in session.scalars(select(Layer).order_by(Layer.position, Layer.name))
        ],
        "sets": [
            set_view(s, set_counts.get(s.id, 0))
            for s in session.scalars(select(CharSet).order_by(CharSet.position, CharSet.name))
        ],
        "types": [type_brief(t, actor) for t in session.scalars(types)],
        "purposes": [purpose_view(p) for p in purposes(session)],
    }
