"""Инвентарные единицы (5.4.2): карточка, правки без документа с откатом, файлы, реестр
(5.4.8), выдача номеров."""

import uuid
from datetime import date
from typing import Any, BinaryIO

from sqlalchemy import Integer, Select, String, bindparam, case, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, UUID, distinct_on
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
    residual_sql,
)
from app.modules.journal import api as journal
from app.modules.system import api as system

EDITABLE = ("responsible", "department", "note", "state", "values", "parent_id")


def visible(actor: Actor) -> Any:
    """Что видит действующий: администратор — всё, «просмотр» — свои здания (2.2)."""
    if actor.is_admin:
        return True
    return Unit.building_id.in_(list(actor.building_ids) or [uuid.uuid4()])


def is_unit_file(session: Session, actor: Actor, file_id: uuid.UUID) -> bool:
    """Фото или документ единицы, которую видит действующий. Гостю по ссылке учёт не открыт
    (5.7.2). Фото из пакета переноса бывает без строки в unit_file — проверяется и оно."""
    if actor.is_guest:
        return False
    linked = select(UnitFile.unit_id).where(UnitFile.file_id == file_id)
    q = select(Unit.id).where(
        visible(actor), or_(Unit.id.in_(linked), Unit.photo_file_id == file_id)
    ).limit(1)
    return session.scalar(q) is not None


def get_unit(
    session: Session, actor: Actor, unit_id: uuid.UUID, for_update: bool = False
) -> Unit:
    """for_update — чтобы изменить карточку: строка блокируется до конца транзакции и читается
    заново — сверка версии видит то, что записало проведение документа (ADR-0003)."""
    unit = (
        session.get(Unit, unit_id, with_for_update=True, populate_existing=True)
        if for_update
        else session.get(Unit, unit_id)
    )
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


def value_sql(at: date) -> Any:
    """value_now в базе — для итогов по тысячам единиц одним агрегатом (8.1, R-036)."""
    return case((Unit.state == "written_off", 0), else_=residual_sql(
        Unit.price, Unit.commissioned_on, Unit.life_months, Unit.value_base, Unit.value_date, at
    ))


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
    unit = get_unit(session, actor, unit_id, for_update=True)
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
        refs=Places(session, actor).refs([unit.place]),
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
    unit = get_unit(session, actor, ch.unit_id, for_update=True)
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
        refs=Places(session, actor).refs([unit.place]),
        before=ch.after,
        after=ch.before,
    )
    return unit


# ---------------------------------------------------------------- файлы


def add_file(
    session: Session, actor: Actor, unit_id: uuid.UUID, stream: BinaryIO, name: str, kind: str
) -> UnitFile:
    admin(actor)
    unit = get_unit(session, actor, unit_id, for_update=True)
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
        refs=Places(session, actor).refs([unit.place]),
    )
    return link


def remove_file(session: Session, actor: Actor, link_id: uuid.UUID) -> Unit:
    admin(actor)
    link = session.get(UnitFile, link_id)
    if link is None:
        raise NotFound("Файл не найден.")
    unit = get_unit(session, actor, link.unit_id, for_update=True)
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
        refs=Places(session, actor).refs([unit.place]),
    )
    return unit


# ---------------------------------------------------------------- номера (4.6 п. 2)


def number_template(session: Session) -> str:
    return str(system.get(session, "inventory_number_template"))


class Numbers:
    """Выдаёт следующие свободные номера; занятые (в том числе списанными) не выдаются.
    reserved — номера, указанные вручную в других строках того же документа: строке без
    номера они не выдаются, в каком бы порядке ни шли строки (R-001)."""

    def __init__(self, session: Session, reserved: set[str] | None = None):
        self.session = session
        self.template = number_template(session)
        self.reserved = set(reserved or ())
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
            if number not in self.taken and number not in self.reserved:
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


def _ranked(
    q: Select[Any], column: Any, titles: dict[Any, str], of: Any
) -> tuple[Select[Any], Any]:
    """Порядок по подписи, которой нет в таблице единиц (наименование типа, название места):
    подписи упорядочиваются здесь же, в Python, как прежде, а база получает ранг ключа —
    двумя массивами, без чужих таблиц и без параметра на каждый ключ (их до 10 000, 8.1)."""
    order = {t: i for i, t in enumerate(sorted(set(titles.values())))}
    keys = list(titles)
    rank = func.unnest(
        bindparam("rank_keys", keys, type_=ARRAY(of)),
        bindparam("rank_values", [order[titles[k]] for k in keys], type_=ARRAY(Integer)),
    ).table_valued("key", "rank").render_derived(name="ranked")
    return q.join(rank, rank.c.key == column), rank.c.rank


def registry(
    session: Session,
    actor: Actor,
    *,
    sort: str = "number",
    offset: int = 0,
    limit: int = 100,
    **filters: Any,
) -> dict[str, Any]:
    # 8.1: до 50 000 единиц и до 20 одновременно работающих — сортировка, страница и итоги
    # считаются в базе, читается только показываемая страница (R-036)
    q = registry_query(session, actor, **filters)
    sums = [func.count()]
    if actor.sees_cost:
        sums += [func.coalesce(func.sum(Unit.price), 0),
                 func.coalesce(func.sum(value_sql(date.today())), 0)]
    total, *money = session.execute(
        q.with_only_columns(*sums, maintain_column_froms=True)
    ).one()
    by = sort.lstrip("-")
    # «просмотр» не видит стоимость и номера (2.2) и не должен узнать их по порядку строк
    # (R-015): по цене и номеру ему сортируется по наименованию, при равных — по ключу записи
    if by == "price" and not actor.sees_cost:
        by = "title"
    if by not in ("title", "place", "state", "commissioned_on", "price", "responsible"):
        by = "number" if actor.sees_inventory_numbers else "title"
    places = Places(session, actor)
    # строки — по кодам символов (COLLATE "C"), как сравнивает их Python: порядок не зависит
    # от языковых настроек базы
    first: Any
    if by == "title":
        type_ids = session.scalars(q.with_only_columns(Unit.type_id).distinct())
        names = {t.id: t.name for t in catalog.types_by_id(session, type_ids).values()}
        q, first = _ranked(q, Unit.type_id, names, UUID)
    elif by == "place":
        keys = list(session.scalars(q.with_only_columns(Unit.place).distinct()))
        places.preload(keys)
        q, first = _ranked(q, Unit.place, {k: places.title(k) for k in keys}, String)
    else:
        first = {
            "number": Unit.number.collate("C"),
            "state": Unit.state.collate("C"),
            "commissioned_on": Unit.commissioned_on,
            "price": Unit.price,
            "responsible": Unit.responsible.collate("C"),
        }[by]
    tie = Unit.number.collate("C") if actor.sees_inventory_numbers else Unit.id
    if sort.startswith("-"):
        first, tie = first.desc(), tie.desc()
    units = list(session.scalars(q.order_by(first, tie).offset(offset).limit(limit)))
    places.preload(u.place for u in units)
    types = catalog.types_by_id(session, {u.type_id for u in units})
    models = catalog.models_by_id(session, {u.model_id for u in units})
    out: dict[str, Any] = {
        "total": total,
        "items": [unit_brief(u, actor, places, types, models) for u in units],
    }
    if actor.sees_cost:
        out["sum_price"], out["sum_value"] = (round(float(m), 2) for m in money)
    return out


def events_at(session: Session, unit_ids: Any, at: date) -> dict[uuid.UUID, UnitEvent]:
    """Последнее событие каждой единицы на дату (место, состояние, оценка тогда). unit_ids —
    список или подзапрос: 50 000 единиц (8.1) лучше отобрать в базе, чем перечислять.
    Последнее — по порядку проведения: даты событий единицы идут по порядку (ADR-0004), а для
    данных, проведённых раньше этого правила, так отчёт на сегодня совпадает с карточкой."""
    if isinstance(unit_ids, list) and not unit_ids:
        return {}
    rows = session.scalars(
        select(UnitEvent)
        .where(UnitEvent.unit_id.in_(unit_ids), UnitEvent.date <= at, UnitEvent.undone.is_(False))
        .order_by(UnitEvent.unit_id, UnitEvent.seq.desc())
        .ext(distinct_on(UnitEvent.unit_id))
    )
    return {e.unit_id: e for e in rows}
