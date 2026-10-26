"""Инвентаризация (5.4.6, С18): ведомость на места → обход с телефона (метки сканируются, что
без метки — отмечается вручную или заводится) → проведение расхождений одним документом:
найденное не на своём месте перемещается, ненайденное — «не найдена» (для разбирательства
или списания), новое ставится на учёт, остатки выравниваются. Ведомость — документ вида
«Инвентаризация»: черновик, пока идёт обход; проведённый — как любой документ, отменяется
обратным.

Что числится, считается по текущему учёту мест ведомости — на момент печати или проведения.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, NotFound
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.inventory import documents as docs
from app.modules.inventory.models import (
    Cell,
    CountDevice,
    CountExtra,
    CountMark,
    CountPlace,
    CountStock,
    Document,
    RoomLabel,
    StockMove,
    Unit,
)
from app.modules.inventory.places import Places, admin, room_key
from app.modules.inventory.rules import doc_title
from app.modules.inventory.units import title_of
from app.modules.journal import api as journal


def _count(
    session: Session, actor: Actor, doc_id: uuid.UUID, for_update: bool = False
) -> Document:
    doc = docs.get_document(session, actor, doc_id, for_update)
    if doc.kind != "inventory":
        raise NotFound("Инвентаризация не найдена.")
    return doc


def _draft(doc: Document) -> None:
    if doc.status != "draft":
        raise Conflict("Инвентаризация уже проведена — отметки не меняются.")


Sent = tuple[uuid.UUID, int]  # устройство и номер отметки (ADR-0006)


def _fresh(session: Session, doc: Document, sent: Sent | None) -> bool:
    """Номер отметки больше последнего принятого от устройства в этой ведомости — запоминает
    его; иначе это опоздавший повтор, и отметку надо пропустить (R-049, ADR-0006). Строка
    устройства держится до конца транзакции: одновременный запрос того же устройства ждёт её
    и сравнивает уже с новым номером. Отказ по отметке откатывает и номер. Без номера отметка
    принимается, как раньше."""
    if sent is None:
        return True
    device, seq = sent
    row = insert(CountDevice).values(document_id=doc.id, device=device, last_seq=seq)
    row = row.on_conflict_do_update(
        index_elements=[CountDevice.document_id, CountDevice.device],
        set_={"last_seq": row.excluded.last_seq},
        where=CountDevice.last_seq < row.excluded.last_seq,
    )
    return session.execute(row.returning(CountDevice.last_seq)).first() is not None


def places_of(session: Session, doc: Document) -> list[str]:
    return list(session.scalars(select(CountPlace.place).where(CountPlace.document_id == doc.id)))


def create_count(
    session: Session,
    actor: Actor,
    places: list[str],
    floor_id: uuid.UUID | None,
    warehouse_id: uuid.UUID | None,
) -> Document:
    """Ведомость на выбранные места (5.4.6 п. 1): этаж (все его помещения), помещения,
    склад (с ячейками)."""
    admin(actor)
    keys = list(dict.fromkeys(places))
    if floor_id is not None:
        floor = building.get_floor(session, actor, floor_id)
        keys += [room_key(r.id) for r in building.live_rooms(session, floor.id)]
    if warehouse_id is not None:
        keys.append(f"w:{warehouse_id}")
        keys += [
            f"c:{c}"
            for c in session.scalars(select(Cell.id).where(Cell.warehouse_id == warehouse_id))
        ]
    known = Places(session, actor)
    keys = list(dict.fromkeys(keys))
    for k in keys:
        known.get(k)  # проверяет, что место есть и доступно
    if not keys:
        raise AppError("Выберите места: этаж, помещения или склад.", field="places")
    doc = docs.create_document(session, actor, "inventory", {})
    for k in keys:
        session.add(CountPlace(document_id=doc.id, place=k))
    session.flush()
    journal.record(
        session,
        actor,
        "inventory.count_create",
        f"Начата «{doc_title(doc.kind, doc.number)}»: мест {len(keys)}",
        entity=f"document:{doc.id}",
    )
    return doc


def _units_in(session: Session, places: list[str]) -> list[Unit]:
    return list(
        session.scalars(
            select(Unit)
            .where(Unit.place.in_(places), Unit.state != "written_off")
            .order_by(Unit.number)
        )
    )


Position = tuple[str, uuid.UUID, uuid.UUID | None]  # место, тип, модель — как хранится остаток


def _stock_in(session: Session, places: list[str]) -> dict[Position, Decimal]:
    """Остатки мест по позициям: каждая модель типа — отдельно (R-021, ADR-0005)."""
    from sqlalchemy import func

    rows = session.execute(
        select(StockMove.place, StockMove.type_id, StockMove.model_id, func.sum(StockMove.qty))
        .where(StockMove.place.in_(places))
        .group_by(StockMove.place, StockMove.type_id, StockMove.model_id)
    ).all()
    return {(p, t, m): Decimal(q) for p, t, m, q in rows if q}


def _counted(session: Session, doc: Document) -> dict[Position, Decimal]:
    return {
        (s.place, s.type_id, s.model_id): Decimal(s.counted)
        for s in session.scalars(select(CountStock).where(CountStock.document_id == doc.id))
    }


def count_view(
    session: Session, actor: Actor, doc_id: uuid.UUID, place: str | None = None
) -> dict[str, Any]:
    """Ведомость и ход обхода: по местам — сколько числится и сколько найдено; по выбранному
    месту — что числится (найдено здесь, найдено в другом месте, не найдено), найденное здесь
    чужое, вещи без метки, остатки."""
    doc = _count(session, actor, doc_id)
    keys = places_of(session, doc)
    known = Places(session, actor)
    units = _units_in(session, keys)
    marks = {
        m.unit_id: m
        for m in session.scalars(select(CountMark).where(CountMark.document_id == doc.id))
    }
    extras = list(session.scalars(select(CountExtra).where(CountExtra.document_id == doc.id)))
    stock = _stock_in(session, keys)
    counted = _counted(session, doc)
    by_place = {k: [u for u in units if u.place == k] for k in keys}
    found_here = {k: [m for m in marks.values() if m.place == k] for k in keys}
    summary_places = []
    for k in keys:
        mine = by_place[k]
        summary_places.append(
            {
                "key": k,
                "title": known.title(k),
                "short": known.get(k).short,
                "expected": len(mine),
                "found": sum(1 for u in mine if u.id in marks),
                "foreign": sum(1 for m in found_here[k] if m.unit_id not in {u.id for u in mine}),
                "extras": sum(1 for e in extras if e.place == k),
            }
        )
    in_scope = {u.id for u in units}
    outside = [m for m in marks.values() if m.unit_id not in in_scope]
    outside_units = {
        u.id: u
        for u in session.scalars(select(Unit).where(Unit.id.in_([m.unit_id for m in outside])))
    }
    total = {
        "expected": len(units),
        "found_in_place": sum(1 for u in units if u.id in marks and marks[u.id].place == u.place),
        "found_elsewhere": sum(1 for u in units if u.id in marks and marks[u.id].place != u.place)
        + len(outside),
        "missing": sum(1 for u in units if u.id not in marks),
        "extras": len(extras),
        "stock_diff": sum(
            1 for key, have in stock.items() if key in counted and counted[key] != have
        ),
    }
    out: dict[str, Any] = {
        **docs.doc_view(session, actor, doc, full=False),
        "places": summary_places,
        "summary": total,
    }
    if place is not None:
        if place not in keys:
            raise AppError("Этого места нет в ведомости.", field="place")
        types = catalog.types_by_id(
            session,
            [u.type_id for u in units]
            + [e.type_id for e in extras]
            + [t for _, t, _ in stock]
            + [u.type_id for u in outside_units.values()],
        )
        models = catalog.models_by_id(
            session,
            [u.model_id for u in [*units, *outside_units.values()] if u.model_id]
            + [m for _, _, m in stock if m],
        )

        def row(u: Unit) -> dict[str, Any]:
            m = marks.get(u.id)
            status = (
                "missing"
                if m is None
                else "here"
                if m.place == place and u.place == place
                else "elsewhere"
                if u.place == place
                else "foreign"
            )
            return {
                "unit_id": u.id,
                "number": u.number,
                "title": title_of(types[u.type_id].name, models.get(u.model_id)),
                "state": u.state,
                "status": status,
                "manual": bool(m and m.manual),
                "found_place": known.title(m.place) if m and m.place != place else "",
                "home_place": known.title(u.place) if u.place != place else "",
            }

        foreign = [
            row(outside_units.get(m.unit_id) or next(x for x in units if x.id == m.unit_id))
            for m in found_here[place]
            if m.unit_id not in {u.id for u in by_place[place]}
        ]
        out["place"] = {
            "key": place,
            "title": known.title(place),
            "items": [row(u) for u in by_place[place]],
            "foreign": foreign,
            "extras": [
                {
                    "id": e.id,
                    "title": types[e.type_id].name,
                    "serial": e.serial,
                    "note": e.note,
                    "photo_file_id": e.photo_file_id,
                }
                for e in extras
                if e.place == place
            ],
            "stock": sorted(
                (
                    {
                        "type_id": t,
                        "model_id": m,
                        "title": title_of(types[t].name, models.get(m)),
                        "unit": types[t].unit,
                        "expected": float(q),
                        "counted": float(counted[(p, t, m)]) if (p, t, m) in counted else None,
                    }
                    for (p, t, m), q in stock.items()
                    if p == place
                ),
                key=lambda s: s["title"],
            ),
        }
    return out


def scan(
    session: Session,
    actor: Actor,
    doc_id: uuid.UUID,
    code: str,
    place: str | None,
    sent: Sent | None = None,
) -> dict[str, Any]:
    """Скан метки при обходе (6.5.8): вещь своего места — «найдена» (зелёным), чужая —
    «не здесь» (жёлтым), неизвестная — красным; метка на двери — переход к помещению.
    Опоздавший повтор — «пропущено» (ADR-0006)."""
    doc = _count(session, actor, doc_id)
    _draft(doc)
    if not _fresh(session, doc, sent):
        return {"result": "skipped"}
    keys = places_of(session, doc)
    code = code.strip().upper()
    if "/Q/" in code:
        code = code.rsplit("/Q/", 1)[1].strip("/")
    door = session.scalar(select(RoomLabel).where(RoomLabel.label_code == code))
    if door is not None:
        key = room_key(door.room_id)
        if key not in keys:
            return {"result": "other_room", "text": "Это помещение не входит в ведомость."}
        return {"result": "room", "place": key, "text": Places(session, actor).title(key)}
    unit = session.scalar(select(Unit).where(Unit.label_code == code))
    if unit is None:
        # номер с наклейки, набранный руками
        unit = session.scalar(select(Unit).where(Unit.number == code))
    if unit is None or unit.state == "written_off":
        return {"result": "unknown", "text": "Метка неизвестна — эта вещь не числится."}
    if place is None or place not in keys:
        raise AppError("Выберите место, где идёт обход.", field="place")
    return mark(session, actor, doc_id, unit.id, place, manual=False)


def mark(
    session: Session,
    actor: Actor,
    doc_id: uuid.UUID,
    unit_id: uuid.UUID,
    place: str,
    manual: bool,
    sent: Sent | None = None,
) -> dict[str, Any]:
    doc = _count(session, actor, doc_id)
    _draft(doc)
    if not _fresh(session, doc, sent):
        return {"result": "skipped"}
    if place not in places_of(session, doc):
        raise AppError("Этого места нет в ведомости.", field="place")
    unit = session.get(Unit, unit_id)
    if unit is None or unit.state == "written_off":
        raise NotFound("Единица не найдена или списана.")
    m = session.get(CountMark, (doc.id, unit.id))
    again = m is not None and m.place == place
    if m is None:
        m = CountMark(document_id=doc.id, unit_id=unit.id)
        session.add(m)
    m.place, m.manual, m.marked_by = place, manual, actor.full_name
    m.marked_at = datetime.now(UTC)
    session.flush()
    t = catalog.get_type(session, unit.type_id)
    known = Places(session, actor)
    result = "again" if again else "here" if unit.place == place else "elsewhere"
    return {
        "result": result,
        "unit_id": unit.id,
        "number": unit.number,
        "title": t.name,
        "text": (
            f"{t.name} № {unit.number}"
            + ("" if unit.place == place else f" — числится: {known.title(unit.place)}")
        ),
    }


def unmark(
    session: Session,
    actor: Actor,
    doc_id: uuid.UUID,
    unit_id: uuid.UUID,
    sent: Sent | None = None,
) -> None:
    doc = _count(session, actor, doc_id)
    _draft(doc)
    if not _fresh(session, doc, sent):
        return
    session.execute(
        delete(CountMark).where(CountMark.document_id == doc.id, CountMark.unit_id == unit_id)
    )


def add_extra(session: Session, actor: Actor, doc_id: uuid.UUID, v: dict[str, Any]) -> CountExtra:
    """Вещь без метки, которая не числится: заведётся при проведении (5.4.6 п. 2)."""
    doc = _count(session, actor, doc_id)
    _draft(doc)
    place = str(v.get("place") or "")
    if place not in places_of(session, doc):
        raise AppError("Этого места нет в ведомости.", field="place")
    try:
        type_id = uuid.UUID(str(v.get("type_id")))
    except ValueError:
        raise AppError("Выберите тип.", field="type_id") from None
    t = catalog.get_type(session, type_id)
    if t.accounting != "piece":
        raise AppError(f"«{t.name}» учитывается количеством — укажите пересчитанный остаток.")
    model_id = uuid.UUID(str(v["model_id"])) if v.get("model_id") else None
    photo = uuid.UUID(str(v["photo_file_id"])) if v.get("photo_file_id") else None
    e = CountExtra(
        document_id=doc.id,
        place=place,
        type_id=t.id,
        model_id=model_id,
        serial=str(v.get("serial") or "")[:100],
        note=str(v.get("note") or "")[:300],
        photo_file_id=photo,
    )
    session.add(e)
    session.flush()
    return e


def remove_extra(session: Session, actor: Actor, doc_id: uuid.UUID, extra_id: uuid.UUID) -> None:
    doc = _count(session, actor, doc_id)
    _draft(doc)
    session.execute(
        delete(CountExtra).where(CountExtra.document_id == doc.id, CountExtra.id == extra_id)
    )


def set_stock(
    session: Session,
    actor: Actor,
    doc_id: uuid.UUID,
    place: str,
    type_id: uuid.UUID,
    model_id: uuid.UUID | None,
    counted: float | None,
    sent: Sent | None = None,
) -> None:
    """Пересчитанный остаток позиции; без модели — позиция без модели (ADR-0005). Опоздавший
    повтор не перезаписывает более новый пересчёт (ADR-0006)."""
    doc = _count(session, actor, doc_id)
    _draft(doc)
    if not _fresh(session, doc, sent):
        return
    if place not in places_of(session, doc):
        raise AppError("Этого места нет в ведомости.", field="place")
    if model_id is not None and catalog.get_model(session, model_id).type_id != type_id:
        raise AppError("Модель другого типа.", field="model_id")
    row = session.scalar(
        select(CountStock).where(
            CountStock.document_id == doc.id,
            CountStock.place == place,
            CountStock.type_id == type_id,
            CountStock.model_id.is_(None) if model_id is None else CountStock.model_id == model_id,
        )
    )
    if counted is None:
        if row is not None:
            session.delete(row)
        return
    if counted < 0:
        raise AppError("Количество — не меньше нуля.", field="counted")
    if row is None:
        row = CountStock(
            document_id=doc.id, place=place, type_id=type_id, model_id=model_id, counted=counted
        )
        session.add(row)
    row.counted = counted


def post_count(session: Session, actor: Actor, doc_id: uuid.UUID, version: int) -> Document:
    """Провести (5.4.6 п. 3): строки документа — из отметок обхода; дальше — как любой
    документ, целиком или никак."""
    admin(actor)
    # расхождения считаются от остатков и мест — их не должен менять другой сеанс (ADR-0003)
    docs.lock(session)
    doc = _count(session, actor, doc_id, for_update=True)
    _draft(doc)
    if doc.version != version:
        from app.core.errors import stale

        raise stale("Инвентаризация")
    keys = places_of(session, doc)
    units = _units_in(session, keys)
    marks = {
        m.unit_id: m
        for m in session.scalars(select(CountMark).where(CountMark.document_id == doc.id))
    }
    lines: list[dict[str, Any]] = []
    for u in units:
        m = marks.pop(u.id, None)
        if m is None:
            if u.state != "not_found":
                lines.append({"unit_id": u.id, "state": "not_found", "note": "не найдена"})
        elif m.place != u.place:
            lines.append(
                {"unit_id": u.id, "to_place": m.place, "note": "найдена не на своём месте"}
            )
        elif u.state == "not_found":
            lines.append({"unit_id": u.id, "to_place": m.place, "note": "найдена"})
    # найдены здесь, а числятся вне ведомости
    for m in marks.values():
        u = session.get(Unit, m.unit_id)
        if u is not None and u.state != "written_off":
            lines.append(
                {"unit_id": u.id, "to_place": m.place, "note": "найдена не на своём месте"}
            )
    for e in session.scalars(select(CountExtra).where(CountExtra.document_id == doc.id)):
        t = catalog.get_type(session, e.type_id)
        lines.append(
            {
                "type_id": e.type_id,
                "model_id": e.model_id,
                "qty": 1,
                "to_place": e.place,
                "price": t.price or 0,
                "serial": e.serial,
                "note": e.note or "не числилась",
                "commissioned_on": doc.date,
            }
        )
    stock = _stock_in(session, keys)
    for (place, type_id, model_id), counted in _counted(session, doc).items():
        diff = counted - stock.get((place, type_id, model_id), Decimal(0))
        position = {"type_id": type_id, "model_id": model_id}
        if diff > 0:
            lines.append({**position, "qty": diff, "to_place": place, "reason": "излишек"})
        elif diff < 0:
            lines.append({**position, "qty": -diff, "from_place": place, "reason": "недостача"})
    if not lines:
        lines.append({"note": "расхождений нет", "reason": "без расхождений"})
    doc = docs.update_document(session, actor, doc.id, doc.version, {"date": date.today()}, lines)
    return docs.post(session, actor, doc.id, doc.version)


# ---------------------------------------------------------------- печать (5.4.6 п. 4)

SIGNATURES = [
    "Председатель комиссии",
    "Член комиссии",
    "Член комиссии",
    "Материально ответственное лицо",
]


def statement_pdf(
    session: Session, actor: Actor, doc_id: uuid.UUID, organization: str
) -> tuple[bytes, str]:
    """Инвентаризационная ведомость: по местам — что числится и отметки обхода; остатки —
    по учёту и фактически; места для подписей комиссии."""
    from app.core import report

    doc = _count(session, actor, doc_id)
    view = count_view(session, actor, doc_id)
    sections = []
    for p in view["places"]:
        detail = count_view(session, actor, doc_id, p["key"])["place"]
        marks = {
            "here": "найдена",
            "elsewhere": "найдена в другом месте",
            "foreign": "найдена здесь",
            "missing": "",
        }
        rows = [
            [
                i + 1,
                x["title"],
                x["number"],
                x["state"] if x["state"] != "in_use" else "в работе",
                marks[x["status"]] + (f" ({x['found_place']})" if x["found_place"] else ""),
            ]
            for i, x in enumerate(detail["items"] + detail["foreign"])
        ]
        rows += [
            [len(rows) + i + 1, f"{e['title']} (не числилась)", "—", "", "найдена"]
            for i, e in enumerate(detail["extras"])
        ]
        sections.append(
            report.Section(
                p["title"], ["№", "Наименование", "Инв. №", "Состояние", "Отметка"], rows
            )
        )
        if detail["stock"]:
            sections.append(
                report.Section(
                    f"{p['title']} — остатки",
                    ["Наименование", "Ед.", "По учёту", "Фактически"],
                    [
                        [
                            s["title"],
                            s["unit"],
                            s["expected"],
                            s["counted"] if s["counted"] is not None else "",
                        ]
                        for s in detail["stock"]
                    ],
                    numeric={2, 3},
                )
            )
    r = report.Report(
        title=f"Инвентаризационная ведомость — {doc_title(doc.kind, doc.number)}",
        subtitle=(
            f"от {doc.date:%d.%m.%Y}; мест: {len(view['places'])}, "
            f"числится единиц: {view['summary']['expected']}"
        ),
        organization=organization,
        sections=sections,
        signatures=SIGNATURES,
    )
    return report.pdf(r), f"Ведомость {doc_title(doc.kind, doc.number)}.pdf"


def act_pdf(
    session: Session, actor: Actor, doc_id: uuid.UUID, organization: str
) -> tuple[bytes, str]:
    """Акт расхождений проведённой инвентаризации: что найдено не там (и перемещено), что не
    найдено, что не числилось (поставлено на учёт), излишки и недостачи."""
    from app.core import report

    doc = _count(session, actor, doc_id)
    if doc.status == "draft":
        raise AppError("Акт расхождений — после проведения инвентаризации.")
    known = Places(session, actor)
    lines = docs.lines_of(session, doc)
    unit_ids = [ln.unit_id for ln in lines if ln.unit_id]
    for ln in lines:
        unit_ids += [uuid.UUID(u) for u in ln.created_units]
    units = {u.id: u for u in session.scalars(select(Unit).where(Unit.id.in_(unit_ids)))}
    types = catalog.types_by_id(
        session, [u.type_id for u in units.values()] + [ln.type_id for ln in lines if ln.type_id]
    )
    models = catalog.models_by_id(session, [ln.model_id for ln in lines if ln.model_id])
    moved, missing, new, stock = [], [], [], []
    for ln in lines:
        u = units.get(ln.unit_id) if ln.unit_id else None
        if u is not None and ln.state == "not_found":
            missing.append([u.number, types[u.type_id].name, known.title(u.place)])
        elif u is not None:
            moved.append(
                [
                    u.number,
                    types[u.type_id].name,
                    known.title(ln.from_place),
                    known.title(ln.to_place),
                ]
            )
        elif ln.reason in ("излишек", "недостача"):
            stock.append(
                [
                    title_of(types[ln.type_id].name, models.get(ln.model_id)),
                    known.title(ln.to_place or ln.from_place),
                    ln.reason,
                    float(ln.qty or 0),
                ]
            )
        elif ln.created_units:
            for cid in ln.created_units:
                nu = units.get(uuid.UUID(cid))
                if nu is not None:
                    new.append(
                        [nu.number, types[nu.type_id].name, known.title(nu.place), ln.serial]
                    )
    r = report.Report(
        title=f"Акт расхождений — {doc_title(doc.kind, doc.number)}",
        subtitle=f"проведена {doc.date:%d.%m.%Y}",
        organization=organization,
        sections=[
            report.Section(
                "Найдено не на своём месте — перемещено",
                ["Инв. №", "Наименование", "Числилась", "Найдена"],
                moved,
            ),
            report.Section(
                "Не найдено — для разбирательства или списания",
                ["Инв. №", "Наименование", "Числилась"],
                missing,
            ),
            report.Section(
                "Не числилось — поставлено на учёт",
                ["Инв. №", "Наименование", "Место", "Серийный №"],
                new,
            ),
            report.Section(
                "Излишки и недостачи",
                ["Наименование", "Место", "Что", "Количество"],
                stock,
                numeric={3},
            ),
        ],
        signatures=SIGNATURES,
    )
    return report.pdf(r), f"Акт расхождений {doc_title(doc.kind, doc.number)}.pdf"
