"""Инвентарные единицы (5.4.2): карточка, правки без документа с откатом, файлы, реестр
(5.4.8), выдача номеров."""

import uuid
from datetime import date
from typing import Any, BinaryIO

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, NotFound, stale
from app.modules.catalog import api as catalog
from app.modules.files import api as files
from app.modules.inventory.models import (
    Cell,
    DocLine,
    Document,
    Unit,
    UnitChange,
    UnitEvent,
    UnitFile,
)
from app.modules.inventory.places import Places, admin
from app.modules.inventory.rules import (
    CARD_STATES,
    STATES,
    doc_title,
    format_number,
    number_value,
    residual,
)
from app.modules.journal import api as journal
from app.modules.system import api as system

EDITABLE = ("responsible", "department", "note", "state", "values", "parent_id")


def visible(actor: Actor) -> Any:
    """Что видит действующий: администратор — всё, «просмотр» — свои здания (2.2)."""
    if actor.is_admin:
        return True
    return Unit.building_id.in_(list(actor.building_ids) or [uuid.uuid4()])


def get_unit(session: Session, actor: Actor, unit_id: uuid.UUID) -> Unit:
    unit = session.get(Unit, unit_id)
    if unit is None or not (
        actor.is_admin or (unit.building_id and actor.can_see_building(unit.building_id))
    ):
        raise NotFound("Инвентарная единица не найдена.")
    return unit


def value_now(unit: Unit, at: date | None = None) -> float:
    if unit.state == "written_off":
        return 0.0
    return residual(
        unit.price,
        unit.commissioned_on,
        unit.life_months,
        unit.value_base,
        unit.value_date,
        at or date.today(),
    )


def title_of(type_name: str, model: Any) -> str:
    return (
        f"{type_name} {model.manufacturer} {model.name}".replace("  ", " ").strip()
        if model
        else type_name
    )


def unit_brief(
    unit: Unit, actor: Actor, places: Places, types: dict, models: dict
) -> dict[str, Any]:
    t = types.get(unit.type_id)
    m = models.get(unit.model_id) if unit.model_id else None
    place = places.get(unit.place) if unit.place else None
    out: dict[str, Any] = {
        "id": unit.id,
        "type_id": unit.type_id,
        "type_name": t.name if t else "",
        "model_id": unit.model_id,
        "model_name": " ".join(p for p in (m.manufacturer, m.name) if p) if m else "",
        "title": title_of(t.name if t else "", m),
        "layer_id": t.layer_id if t else None,
        "serial": unit.serial,
        "place": place.view() if place else None,
        "state": unit.state,
        "state_title": STATES.get(unit.state, unit.state),
        "responsible": unit.responsible,
        "department": unit.department,
        "commissioned_on": unit.commissioned_on,
        "parent_id": unit.parent_id,
        "photo_url": f"/api/files/{unit.photo_file_id}" if unit.photo_file_id else None,
        "version": unit.version,
    }
    # «просмотр» не видит стоимость и инвентарные номера (2.2)
    if actor.sees_inventory_numbers:
        out["number"] = unit.number
        out["label_code"] = unit.label_code
    if actor.sees_cost:
        out["price"] = float(unit.price or 0)
        out["value"] = value_now(unit)
        out["life_months"] = unit.life_months
    return out


def unit_view(session: Session, actor: Actor, unit: Unit) -> dict[str, Any]:
    places = Places(session, actor)
    t = catalog.get_type(session, unit.type_id)
    m = catalog.get_model(session, unit.model_id) if unit.model_id else None
    out = unit_brief(unit, actor, places, {t.id: t}, {m.id: m} if m else {})
    chars = catalog.characteristics_of(session, t)
    type_values = catalog.values_of(session, type_id=t.id)
    model_values = catalog.values_of(session, model_id=m.id) if m else {}
    out["characteristics"] = [
        {
            "id": c.id,
            "name": c.name,
            "kind": c.kind,
            "unit": c.unit,
            "choices": c.choices,
            "level": c.level,
            "required": c.required,
            "value": (unit.values or {}).get(str(c.id))
            if c.level == "item"
            else (model_values if c.level == "model" else type_values).get(c.id),
        }
        for c in chars
    ]
    out["note"] = unit.note
    out["written_off_on"] = unit.written_off_on
    out["writeoff_reason"] = unit.writeoff_reason
    out["files"] = [
        {**files.view(files.get(session, f.file_id)), "kind": f.kind, "link_id": f.id}
        for f in session.scalars(
            select(UnitFile).where(UnitFile.unit_id == unit.id).order_by(UnitFile.created_at)
        )
    ]
    parent = session.get(Unit, unit.parent_id) if unit.parent_id else None
    out["parent"] = (
        {
            "id": parent.id,
            "title": catalog.get_type(session, parent.type_id).name,
            "number": parent.number if actor.sees_inventory_numbers else None,
        }
        if parent
        else None
    )
    children = list(session.scalars(select(Unit).where(Unit.parent_id == unit.id)))
    ctypes = catalog.types_by_id(session, [c.type_id for c in children])
    out["children"] = [
        {
            "id": c.id,
            "title": ctypes[c.type_id].name,
            "number": c.number if actor.sees_inventory_numbers else None,
        }
        for c in children
    ]
    out["changes"] = [
        {
            "id": ch.id,
            "at": ch.at,
            "actor": ch.actor_name,
            "before": ch.before,
            "after": ch.after,
            "rolled_back": ch.rolled_back,
            "can_roll_back": actor.is_admin and _can_roll_back(unit, ch),
        }
        for ch in session.scalars(
            select(UnitChange).where(UnitChange.unit_id == unit.id).order_by(UnitChange.at.desc())
        )
    ]
    out["movements"] = movements(session, actor, unit, places)
    if actor.sees_cost:
        out["value_base"] = float(unit.value_base) if unit.value_base is not None else None
        out["value_date"] = unit.value_date
    return out


def movements(session: Session, actor: Actor, unit: Unit, places: Places) -> list[dict[str, Any]]:
    """Документы движения единицы (вкладка «Движение»)."""
    rows = session.execute(
        select(Document, DocLine)
        .join(DocLine, DocLine.document_id == Document.id)
        .where(or_(DocLine.unit_id == unit.id, DocLine.created_units.contains([str(unit.id)])))
        .where(Document.status != "draft")
        .order_by(Document.date.desc(), Document.posted_at.desc())
    ).all()
    out = []
    for doc, line in rows:
        out.append(
            {
                "document_id": doc.id,
                "title": doc_title(doc.kind, doc.number),
                "kind": doc.kind,
                "status": doc.status,
                "date": doc.date,
                "from": places.title(line.from_place or doc.from_place),
                "to": places.title(line.to_place or doc.to_place),
            }
        )
    return out


# ---------------------------------------------------------------- правки карточки


def _current(unit: Unit, key: str) -> Any:
    v = getattr(unit, key)
    return str(v) if isinstance(v, uuid.UUID) else v


def _can_roll_back(unit: Unit, ch: UnitChange) -> bool:
    if ch.rolled_back:
        return False
    for k, v in ch.after.items():
        if k == "values":
            if any((unit.values or {}).get(c) != val for c, val in v.items()):
                return False
        elif _current(unit, k) != v:
            return False
    return True


def update_unit(
    session: Session, actor: Actor, unit_id: uuid.UUID, values: dict[str, Any], version: int
) -> Unit:
    admin(actor)
    unit = get_unit(session, actor, unit_id)
    if unit.version != version:
        raise stale("Инвентарную единицу")
    if unit.state == "written_off":
        raise Conflict("Единица списана — её карточка не правится.")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for key, raw in values.items():
        if key not in EDITABLE:
            raise AppError("Место, количество и стоимость меняются только документами.", field=key)
        if key == "state":
            if raw not in CARD_STATES or unit.state not in CARD_STATES:
                raise AppError(
                    "В карточке состояние — только «в работе» или «неисправна»; ремонт и "
                    "списание — документами.",
                    field="state",
                )
            new: Any = raw
        elif key == "values":
            t = catalog.get_type(session, unit.type_id)
            chars = {
                str(c.id): c for c in catalog.characteristics_of(session, t) if c.level == "item"
            }
            changed_b, changed_a = {}, {}
            current = dict(unit.values or {})
            for cid, v in (raw or {}).items():
                ch = chars.get(cid)
                if ch is None:
                    raise AppError("Такой характеристики у вещи этого типа нет.", field="values")
                parsed = catalog.parse_value(ch, v)
                if current.get(cid) != parsed:
                    changed_b[cid], changed_a[cid] = current.get(cid), parsed
                    if parsed is None:
                        current.pop(cid, None)
                    else:
                        current[cid] = parsed
            if changed_a:
                before["values"], after["values"] = changed_b, changed_a
                unit.values = current
            continue
        elif key == "parent_id":
            new = _parent(session, actor, unit, raw)
            new = str(new) if new else None
        else:
            new = str(raw or "").strip()[: 150 if key != "note" else 5000]
        old = _current(unit, key)
        if old != new:
            before[key], after[key] = old, new
            setattr(unit, key, uuid.UUID(new) if key == "parent_id" and new else new)
    if not after:
        return unit
    unit.version += 1
    session.add(
        UnitChange(
            id=uuid.uuid4(), unit_id=unit.id, actor_name=actor.full_name, before=before, after=after
        )
    )
    journal.record(
        session,
        actor,
        "inventory.unit_edit",
        f"Карточка {unit.number}: изменено — {', '.join(_FIELD_TITLES.get(k, k) for k in after)}",
        entity=f"unit:{unit.id}",
        before=before,
        after=after,
    )
    return unit


_FIELD_TITLES = {
    "responsible": "ответственный",
    "department": "подразделение",
    "note": "примечание",
    "state": "состояние",
    "values": "характеристики",
    "parent_id": "в составе",
}


def _parent(session: Session, actor: Actor, unit: Unit, raw: Any) -> uuid.UUID | None:
    if not raw:
        return None
    parent = get_unit(session, actor, uuid.UUID(str(raw)))
    if parent.id == unit.id:
        raise AppError("Единица не может входить в саму себя.", field="parent_id")
    if parent.parent_id:
        raise AppError("Та единица сама входит в состав другой — вкладывать глубже нельзя.")
    if session.scalar(select(func.count()).select_from(Unit).where(Unit.parent_id == unit.id)):
        raise AppError("В эту единицу входят другие — её нельзя вложить.")
    if parent.place != unit.place:
        raise AppError("Единица в составе другой числится там же — сначала переместите её.")
    return parent.id


def roll_back(session: Session, actor: Actor, change_id: uuid.UUID) -> Unit:
    admin(actor)
    ch = session.get(UnitChange, change_id)
    if ch is None:
        raise NotFound("Правка не найдена.")
    unit = get_unit(session, actor, ch.unit_id)
    if not _can_roll_back(unit, ch):
        raise Conflict("С тех пор эти поля меняли — откатить эту правку нельзя.")
    for k, v in ch.before.items():
        if k == "values":
            current = dict(unit.values or {})
            for cid, val in v.items():
                if val is None:
                    current.pop(cid, None)
                else:
                    current[cid] = val
            unit.values = current
        else:
            setattr(unit, k, uuid.UUID(v) if k == "parent_id" and v else v)
    ch.rolled_back = True
    unit.version += 1
    session.add(
        UnitChange(
            id=uuid.uuid4(),
            unit_id=unit.id,
            actor_name=actor.full_name,
            before=ch.after,
            after=ch.before,
            rolled_back=False,
        )
    )
    journal.record(
        session,
        actor,
        "inventory.unit_rollback",
        f"Карточка {unit.number}: откат правки от {ch.at:%d.%m.%Y %H:%M}",
        entity=f"unit:{unit.id}",
        before=ch.after,
        after=ch.before,
    )
    return unit


# ---------------------------------------------------------------- файлы


def add_file(
    session: Session, actor: Actor, unit_id: uuid.UUID, stream: BinaryIO, name: str, kind: str
) -> UnitFile:
    admin(actor)
    unit = get_unit(session, actor, unit_id)
    if kind == "photo":
        limit = int(system.get(session, "photo_max_mb")) * 1024 * 1024
        record = files.store(session, actor, stream, name, {"jpeg", "png", "webp", "heic"}, limit)
    else:
        limit = int(system.get(session, "document_max_mb")) * 1024 * 1024
        record = files.store(
            session, actor, stream, name, {"pdf", "jpeg", "png", "webp", "heic"}, limit
        )
    link = UnitFile(id=uuid.uuid4(), unit_id=unit.id, file_id=record.id, kind=kind)
    session.add(link)
    if kind == "photo" and record.content_type != "image/heic":
        unit.photo_file_id = record.id
    unit.version += 1
    journal.record(
        session,
        actor,
        "inventory.unit_file",
        f"Карточка {unit.number}: {'фото' if kind == 'photo' else 'файл'} «{record.name}»",
        entity=f"unit:{unit.id}",
    )
    return link


def remove_file(session: Session, actor: Actor, link_id: uuid.UUID) -> Unit:
    admin(actor)
    link = session.get(UnitFile, link_id)
    if link is None:
        raise NotFound("Файл не найден.")
    unit = get_unit(session, actor, link.unit_id)
    if unit.photo_file_id == link.file_id:
        unit.photo_file_id = None
    session.delete(link)
    unit.version += 1
    journal.record(
        session,
        actor,
        "inventory.unit_file_remove",
        f"Карточка {unit.number}: убран файл",
        entity=f"unit:{unit.id}",
    )
    return unit


# ---------------------------------------------------------------- номера (4.6 п. 2)


def number_template(session: Session) -> str:
    return str(system.get(session, "inventory_number_template"))


class Numbers:
    """Выдаёт следующие свободные номера; занятые (в том числе списанными) не выдаются."""

    def __init__(self, session: Session):
        self.session = session
        self.template = number_template(session)
        taken = [n for n in session.scalars(select(Unit.number))]
        self.taken = set(taken)
        values = [v for v in (number_value(self.template, n) for n in taken) if v is not None]
        self.next = (max(values) if values else 0) + 1

    def check(self, number: str) -> str:
        number = number.strip()
        if not number:
            raise AppError("Пустой инвентарный номер.")
        if number in self.taken:
            raise AppError(f"Инвентарный номер {number} уже занят.")
        self.taken.add(number)
        return number

    def issue(self) -> str:
        while True:
            number = format_number(self.template, self.next)
            self.next += 1
            if number not in self.taken:
                self.taken.add(number)
                return number


# ---------------------------------------------------------------- реестр (5.4.8)


def registry_query(
    session: Session,
    actor: Actor,
    *,
    building_id: uuid.UUID | None = None,
    floor_id: uuid.UUID | None = None,
    place: str | None = None,
    layer_id: uuid.UUID | None = None,
    type_id: uuid.UUID | None = None,
    state: str | None = None,
    responsible: str | None = None,
    department: str | None = None,
    since: date | None = None,
    until: date | None = None,
    text: str | None = None,
    written_off: bool = False,
    ids: list[uuid.UUID] | None = None,
) -> Select[Any]:
    q = select(Unit).where(visible(actor))
    if ids is not None:
        q = q.where(Unit.id.in_(ids))
    if not written_off and state != "written_off":
        q = q.where(Unit.state != "written_off")
    if building_id:
        q = q.where(Unit.building_id == building_id)
    if floor_id:
        q = q.where(Unit.floor_id == floor_id)
    if place:
        if place.startswith("w:"):
            cells = [
                f"c:{c}"
                for c in session.scalars(
                    select(Cell.id).where(Cell.warehouse_id == uuid.UUID(place[2:]))
                )
            ]
            q = q.where(Unit.place.in_([place, *cells]))
        else:
            q = q.where(Unit.place == place)
    if layer_id:
        q = q.where(Unit.type_id.in_(catalog.type_ids(session, layer_id=layer_id)))
    if type_id:
        q = q.where(Unit.type_id == type_id)
    if state:
        q = q.where(Unit.state == state)
    if responsible:
        q = q.where(Unit.responsible.ilike(f"%{responsible}%"))
    if department:
        q = q.where(Unit.department.ilike(f"%{department}%"))
    if since:
        q = q.where(Unit.commissioned_on >= since)
    if until:
        q = q.where(Unit.commissioned_on <= until)
    if text:
        t = text.strip()
        conds = [Unit.serial.ilike(f"%{t}%"), Unit.type_id.in_(catalog.type_ids(session, text=t))]
        if actor.sees_inventory_numbers:
            conds.append(Unit.number.ilike(f"%{t}%"))
        q = q.where(or_(*conds))
    return q


def registry(
    session: Session,
    actor: Actor,
    *,
    sort: str = "number",
    offset: int = 0,
    limit: int = 100,
    **filters: Any,
) -> dict[str, Any]:
    q = registry_query(session, actor, **filters)
    units = list(session.scalars(q))
    types = catalog.types_by_id(session, [u.type_id for u in units])
    models = catalog.models_by_id(session, [u.model_id for u in units])
    places = Places(session, actor)
    key = {
        "number": lambda u: u.number,
        "title": lambda u: (types[u.type_id].name, u.number),
        "place": lambda u: (places.title(u.place), u.number),
        "state": lambda u: (u.state, u.number),
        "commissioned_on": lambda u: (u.commissioned_on, u.number),
        "price": lambda u: (float(u.price or 0), u.number),
        "responsible": lambda u: (u.responsible, u.number),
    }.get(sort.lstrip("-"), lambda u: u.number)
    if not actor.sees_inventory_numbers and sort.lstrip("-") == "number":
        key = lambda u: (types[u.type_id].name, str(u.id))  # noqa: E731
    units.sort(key=key, reverse=sort.startswith("-"))
    out: dict[str, Any] = {
        "total": len(units),
        "items": [
            unit_brief(u, actor, places, types, models) for u in units[offset : offset + limit]
        ],
    }
    if actor.sees_cost:
        out["sum_price"] = round(sum(float(u.price or 0) for u in units), 2)
        out["sum_value"] = round(sum(value_now(u) for u in units), 2)
    return out


def events_at(session: Session, unit_ids: list[uuid.UUID], at: date) -> dict[uuid.UUID, UnitEvent]:
    """Последнее событие каждой единицы на дату (место, состояние, оценка тогда)."""
    if not unit_ids:
        return {}
    rows = session.scalars(
        select(UnitEvent)
        .where(UnitEvent.unit_id.in_(unit_ids), UnitEvent.date <= at, UnitEvent.undone.is_(False))
        .order_by(UnitEvent.unit_id, UnitEvent.date, UnitEvent.seq)
    )
    out: dict[uuid.UUID, UnitEvent] = {}
    for e in rows:
        out[e.unit_id] = e
    return out
