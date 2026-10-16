"""Учёт имущества (5.4) — программный интерфейс для других модулей и связи с модулями ниже."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import search
from app.core.actor import Actor
from app.core.errors import AppError, Conflict, NotFound
from app.modules.catalog import api as catalog
from app.modules.inventory import documents as docs
from app.modules.inventory.documents import on_units_changed
from app.modules.inventory.models import (
    Cell,
    Document,
    RoomLabel,
    StockMove,
    Unit,
    UnitEvent,
    Warehouse,
)
from app.modules.inventory.places import Places, admin, label_code, room_key
from app.modules.inventory.rules import doc_title
from app.modules.inventory.units import title_of, visible

__all__ = ["on_units_changed", "room_key"]
from app.modules.system import api as system

# ---------------------------------------------------------------- настройки (7.1)


def _template(value: Any) -> str:
    text = str(value or "").strip()
    if not text.endswith("0") or len(text) > 30:
        raise AppError("Вид номера — цифры нулями в конце, например 000000 или ИН-0000.")
    return text


def _number(low: float, high: float, what: str) -> Any:
    def check(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise AppError(f"{what}: нужно число.") from None
        if not low <= v <= high:
            raise AppError(f"{what}: от {low:g} до {high:g}.")
        return v

    return check


def register_settings() -> None:
    S = system.SettingDef
    system.register("inventory_number_template", S("Вид инвентарного номера", "000000", _template))
    system.register("label_width_mm", S("Наклейка: ширина, мм", 40, _number(15, 120, "Ширина")))
    system.register("label_height_mm", S("Наклейка: высота, мм", 25, _number(10, 100, "Высота")))
    system.register(
        "label_sheet_cols", S("Лист А4: наклеек в ряду", 5, _number(1, 10, "Наклеек в ряду"))
    )
    system.register("label_sheet_rows", S("Лист А4: рядов", 11, _number(1, 30, "Рядов")))
    system.register("label_sheet_top_mm", S("Лист А4: поле сверху, мм", 11, _number(0, 50, "Поле")))
    system.register("label_sheet_left_mm", S("Лист А4: поле слева, мм", 5, _number(0, 50, "Поле")))
    system.register(
        "label_sheet_gap_mm", S("Лист А4: промежуток, мм", 0, _number(0, 20, "Промежуток"))
    )
    system.register("photo_max_mb", S("Фото — до, МБ", 15, _number(1, 100, "Размер фото")))
    system.register(
        "document_max_mb", S("Документ — до, МБ", 25, _number(1, 200, "Размер документа"))
    )


def label_settings(session: Session) -> dict[str, Any]:
    keys = (
        "organization_name",
        "label_width_mm",
        "label_height_mm",
        "label_sheet_cols",
        "label_sheet_rows",
        "label_sheet_top_mm",
        "label_sheet_left_mm",
        "label_sheet_gap_mm",
    )
    return {k: system.get(session, k) for k in keys}


# ---------------------------------------------------------------- связи с модулями ниже


def type_usage(session: Session, type_id: uuid.UUID | None, model_id: uuid.UUID | None) -> int:
    """Тип или модель, по которым есть учёт, не удаляются — только в архив (5.2.2)."""
    units = select(func.count()).select_from(Unit)
    moves = select(func.count()).select_from(StockMove)
    if type_id is not None:
        units, moves = (
            units.where(Unit.type_id == type_id),
            moves.where(StockMove.type_id == type_id),
        )
    if model_id is not None:
        units, moves = (
            units.where(Unit.model_id == model_id),
            moves.where(StockMove.model_id == model_id),
        )
    return (session.scalar(units) or 0) + (session.scalar(moves) or 0)


def rooms_continued(
    session: Session, actor: Actor, continued: dict[uuid.UUID, uuid.UUID | None]
) -> None:
    """Помещения объединили (5.1.6 п. 3): единицы и остатки — к продолжающему помещению."""
    places = Places(session, actor)
    today = date.today()
    for old, new in continued.items():
        if new is None:
            continue
        src, dst = room_key(old), room_key(new)
        target = places.get(dst)
        for unit in session.scalars(select(Unit).where(Unit.place == src)):
            unit.place, unit.building_id, unit.floor_id = dst, target.building_id, target.floor_id
            unit.version += 1
            session.add(
                UnitEvent(
                    unit_id=unit.id,
                    document_id=None,
                    date=today,
                    kind="room_merge",
                    place=dst,
                    building_id=target.building_id,
                    floor_id=target.floor_id,
                    state=unit.state,
                    value_base=unit.value_base,
                    value_date=unit.value_date,
                    undone=False,
                )
            )
        rows = session.execute(
            select(
                StockMove.type_id,
                StockMove.model_id,
                func.sum(StockMove.qty),
                func.sum(StockMove.amount),
            )
            .where(StockMove.place == src)
            .group_by(StockMove.type_id, StockMove.model_id)
        ).all()
        for type_id, model_id, qty, amount in rows:
            if not qty:
                continue
            for place, sign in ((src, -1), (dst, 1)):
                session.add(
                    StockMove(
                        document_id=None,
                        line_id=None,
                        date=today,
                        place=place,
                        building_id=target.building_id,
                        floor_id=target.floor_id if place == dst else None,
                        type_id=type_id,
                        model_id=model_id,
                        qty=Decimal(qty) * sign,
                        amount=Decimal(amount) * sign,
                    )
                )


def building_guard(session: Session, building_id: uuid.UUID) -> None:
    if session.scalar(
        select(func.count()).select_from(Warehouse).where(Warehouse.building_id == building_id)
    ):
        raise Conflict("К зданию привязаны склады — сначала перенесите или уберите их.")


def search_units(session: Session, actor: Actor, query: str) -> list[search.Hit]:
    q = query.strip()
    conds = [Unit.serial.ilike(f"%{q}%"), Unit.type_id.in_(catalog.type_ids(session, text=q))]
    if actor.sees_inventory_numbers:
        conds.append(Unit.number.ilike(f"%{q}%"))
    units = list(
        session.scalars(
            select(Unit).where(visible(actor), Unit.state != "written_off", or_(*conds)).limit(15)
        )
    )
    types = catalog.types_by_id(session, [u.type_id for u in units])
    places = Places(session, actor)
    return [
        search.Hit(
            group="Имущество",
            title=f"{types[u.type_id].name}"
            + (f" № {u.number}" if actor.sees_inventory_numbers else ""),
            subtitle=places.title(u.place),
            href=f"/property?card=unit:{u.id}",
        )
        for u in units
    ]


def resolve_label(session: Session, actor: Actor, code: str) -> dict[str, Any]:
    """QR-метка → что это (5.4.7): ссылка постоянная, данных о вещи в ней нет."""
    code = code.strip().upper()
    unit = session.scalar(select(Unit).where(Unit.label_code == code))
    if unit is not None and (
        actor.is_admin or (unit.building_id and actor.can_see_building(unit.building_id))
    ):
        return {"kind": "unit", "id": unit.id, "href": f"/property?card=unit:{unit.id}"}
    wh = session.scalar(select(Warehouse).where(Warehouse.label_code == code))
    if wh is not None and actor.is_admin:
        return {"kind": "warehouse", "id": wh.id, "href": f"/warehouse?place=w:{wh.id}"}
    cell = session.scalar(select(Cell).where(Cell.label_code == code))
    if cell is not None and actor.is_admin:
        return {"kind": "cell", "id": cell.id, "href": f"/warehouse?place=c:{cell.id}"}
    door = session.scalar(select(RoomLabel).where(RoomLabel.label_code == code))
    if door is not None:
        try:
            room = Places(session, actor).get(room_key(door.room_id))
        except (NotFound, AppError):
            room = None
        if room is not None:
            return {
                "kind": "room",
                "id": door.room_id,
                "href": f"/plan/{room.building_id}/{room.floor_id}?room={door.room_id}&mode=place",
            }
    raise NotFound("Метка не найдена — или эта вещь вам недоступна.")


def room_label(session: Session, room_id: uuid.UUID) -> str:
    """Код метки на двери помещения; заводится при первой печати."""
    row = session.get(RoomLabel, room_id)
    if row is None:
        row = RoomLabel(room_id=room_id, label_code=label_code())
        session.add(row)
        session.flush()
    return row.label_code


# ---------------------------------------------------------------- для связи с планом (5.5)


def units_by_id(session: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, Unit]:
    if not ids:
        return {}
    return {u.id: u for u in session.scalars(select(Unit).where(Unit.id.in_(ids)))}


def floor_units(session: Session, actor: Actor, floor_id: uuid.UUID) -> list[Unit]:
    """Единицы, что числятся в помещениях этажа (не списанные)."""
    return list(
        session.scalars(
            select(Unit)
            .where(
                visible(actor),
                Unit.floor_id == floor_id,
                Unit.place.like("r:%"),
                Unit.state != "written_off",
            )
            .order_by(Unit.number)
        )
    )


def unit_briefs(session: Session, actor: Actor, units: list[Unit]) -> list[dict[str, Any]]:
    types = catalog.types_by_id(session, [u.type_id for u in units])
    models = catalog.models_by_id(session, [u.model_id for u in units if u.model_id])
    numbers = actor.sees_inventory_numbers
    return [
        {
            "id": u.id,
            "number": u.number if numbers else "",
            "title": title_of(types[u.type_id].name, models.get(u.model_id)),
            "type_id": u.type_id,
            "model_id": u.model_id,
            "parent_id": u.parent_id,
            "state": u.state,
            "place": u.place,
            "room_id": u.place[2:] if u.place.startswith("r:") else None,
        }
        for u in units
    ]


def room_stock(session: Session, floor_id: uuid.UUID) -> dict[tuple[str, uuid.UUID], Decimal]:
    """Остатки количественного учёта по помещениям этажа: (место, тип) → количество."""
    rows = session.execute(
        select(StockMove.place, StockMove.type_id, func.sum(StockMove.qty))
        .where(StockMove.floor_id == floor_id, StockMove.place.like("r:%"))
        .group_by(StockMove.place, StockMove.type_id)
    ).all()
    return {(place, type_id): Decimal(qty) for place, type_id, qty in rows if qty}


def storage_units(session: Session, type_ids: list[uuid.UUID]) -> list[Unit]:
    """Единицы на складах и в ячейках (не списанные, не в составе другой) — что можно выдать
    (спецификация и применение проекта, 5.3.6, 5.5)."""
    if not type_ids:
        return []
    return list(
        session.scalars(
            select(Unit)
            .where(
                Unit.type_id.in_(type_ids),
                or_(Unit.place.like("w:%"), Unit.place.like("c:%")),
                Unit.state.in_(["storage", "in_use"]),
                Unit.parent_id.is_(None),
            )
            .order_by(Unit.number)
        )
    )


def storage_stock(session: Session, type_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    """Остатки количественного учёта на складах по типам."""
    if not type_ids:
        return {}
    rows = session.execute(
        select(StockMove.type_id, func.sum(StockMove.qty))
        .where(
            StockMove.type_id.in_(type_ids),
            or_(StockMove.place.like("w:%"), StockMove.place.like("c:%")),
        )
        .group_by(StockMove.type_id)
    ).all()
    return {t: Decimal(q) for t, q in rows if q}


def place_titles(session: Session, actor: Actor, keys: list[str]) -> dict[str, str]:
    places = Places(session, actor)
    return {k: places.title(k) for k in set(keys)}


def doc_brief(doc: Document) -> dict[str, Any]:
    return {"id": doc.id, "title": doc_title(doc.kind, doc.number)}


def post_document(
    session: Session,
    actor: Actor,
    kind: str,
    header: dict[str, Any],
    lines: list[dict[str, Any]],
) -> Document:
    """Составить документ и сразу провести (целиком или никак, 5.4.4)."""
    admin(actor)
    doc = docs.create_document(session, actor, kind, header)
    doc = docs.update_document(session, actor, doc.id, doc.version, {}, lines)
    return docs.post(session, actor, doc.id, doc.version)


def created_units(session: Session, doc: Document) -> list[list[Unit]]:
    """Единицы, заведённые документом, — по строкам."""
    out = []
    for line in docs.lines_of(session, doc):
        ids = [uuid.UUID(i) for i in line.created_units]
        found = units_by_id(session, ids)
        out.append([found[i] for i in ids if i in found])
    return out


# ------------------------------------------------- для отчётов (5.6) и выгрузки (7.4)


def registry_rows(session: Session, actor: Actor, **filters: Any) -> list[dict[str, Any]]:
    from app.modules.inventory import units

    return units.registry(session, actor, limit=100_000, **filters)["items"]


def registry_xlsx(session: Session, actor: Actor, **filters: Any) -> bytes:
    from app.modules.inventory import excel

    return excel.registry_export(registry_rows(session, actor, **filters), actor)


def balance_rows(
    session: Session,
    actor: Actor,
    at: date | None = None,
    place: str | None = None,
    building_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    return docs.balances(session, actor, place=place, at=at, building_id=building_id)


def cost_statement(
    session: Session, actor: Actor, at: date, group_by: list[str], building_id: uuid.UUID | None
) -> dict[str, Any]:
    from app.modules.inventory import cost

    return cost.statement(session, actor, at, group_by, building_id)


def cost_xlsx(statement: dict[str, Any]) -> bytes:
    from app.modules.inventory import excel

    return excel.statement_export(statement)


def movement_rows(
    session: Session, actor: Actor, since: date, until: date, building_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Движение за период: строки проведённых документов."""
    admin(actor)
    from app.modules.inventory.models import DocLine

    rows = session.execute(
        select(Document, DocLine)
        .join(DocLine, DocLine.document_id == Document.id)
        .where(Document.status != "draft", Document.date >= since, Document.date <= until)
        .order_by(Document.date, Document.kind, Document.number, DocLine.position)
    ).all()
    unit_ids = [ln.unit_id for _, ln in rows if ln.unit_id]
    units_ = units_by_id(session, unit_ids)
    types = catalog.types_by_id(
        session, [ln.type_id for _, ln in rows if ln.type_id] + [u.type_id for u in units_.values()]
    )
    places = Places(session, actor)
    out = []
    for doc, ln in rows:
        u = units_.get(ln.unit_id) if ln.unit_id else None
        t = types.get(u.type_id if u else ln.type_id) if (u or ln.type_id) else None
        if building_id is not None:
            touched = [
                places.get(k).building_id
                for k in (
                    ln.from_place,
                    ln.to_place,
                    doc.from_place,
                    doc.to_place,
                    u.place if u else None,
                )
                if k
            ]
            if building_id not in touched:
                continue
        out.append(
            {
                "date": doc.date,
                "document": doc_title(doc.kind, doc.number),
                "status": "отменён" if doc.status == "cancelled" else "",
                "what": (t.name if t else "") + (f" № {u.number}" if u else ""),
                "qty": float(ln.qty or 0) if not u else 1,
                "unit": t.unit if t else "",
                "from": places.title(ln.from_place or doc.from_place),
                "to": places.title(ln.to_place or doc.to_place),
                "amount": float((ln.price or 0) * (ln.qty or 0)),
                "note": ln.reason or ln.note,
            }
        )
    return out


def document_pdf(session: Session, actor: Actor, doc_id: uuid.UUID) -> tuple[bytes, str]:
    from app.modules.inventory import printing

    doc = docs.get_document(session, actor, doc_id)
    view = docs.doc_view(session, actor, doc)
    data = printing.document_pdf(view, str(system.get(session, "organization_name") or ""))
    return data, f"{doc_title(doc.kind, doc.number)}.pdf"


def document_choices(
    session: Session, actor: Actor, kind: str | None = None
) -> list[dict[str, Any]]:
    return [
        {"id": d["id"], "title": f"{d['title']} от {d['date']:%d.%m.%Y}", "status": d["status"]}
        for d in docs.documents(session, actor, kind=kind, limit=500)
    ]


def count_pdf(session: Session, actor: Actor, doc_id: uuid.UUID, what: str) -> tuple[bytes, str]:
    from app.modules.inventory import counts

    org = str(system.get(session, "organization_name") or "")
    if what == "act":
        return counts.act_pdf(session, actor, doc_id, org)
    return counts.statement_pdf(session, actor, doc_id, org)


def place_labels_pdf(session: Session, actor: Actor, place: str, base_url: str) -> bytes:
    """Метки на место (помещение — с меткой на дверь)."""
    from app.modules.inventory import printing

    admin(actor)
    known = Places(session, actor)
    p = known.get(place)
    rows = registry_rows(session, actor, place=place)
    items = [{"code": r["label_code"], "number": r["number"], "title": r["title"]} for r in rows]
    if p.room_id:
        items.insert(0, {"code": room_label(session, p.room_id), "number": "", "title": p.title})
    if not items:
        raise AppError("В месте нечего метить.")
    return printing.labels_pdf(items, label_settings(session), base_url, "sheet")


def place_title(session: Session, actor: Actor, key: str) -> str:
    return Places(session, actor).title(key)


def counts_with_state(session: Session, states: list[str], building_id: uuid.UUID | None) -> int:
    q = select(func.count()).select_from(Unit).where(Unit.state.in_(states))
    if building_id is not None:
        q = q.where(Unit.building_id == building_id)
    return session.scalar(q) or 0


def latest_documents(session: Session, actor: Actor, limit: int = 8) -> list[dict[str, Any]]:
    return docs.documents(session, actor, limit=limit)


def unit_files(session: Session, building_id: uuid.UUID | None) -> list[tuple[str, uuid.UUID, str]]:
    """Файлы имущества для полной выгрузки: (папка, файл, подпись)."""
    from app.modules.inventory.models import DocFile, UnitFile

    out: list[tuple[str, uuid.UUID, str]] = []
    q = select(UnitFile, Unit).join(Unit, Unit.id == UnitFile.unit_id)
    if building_id is not None:
        q = q.where(Unit.building_id == building_id)
    for f, u in session.execute(q).all():
        out.append(("имущество", f.file_id, f"{u.number}"))
    for u in session.scalars(select(Unit).where(Unit.photo_file_id.is_not(None))):
        if building_id is None or u.building_id == building_id:
            out.append(("имущество", u.photo_file_id, f"{u.number} фото"))  # type: ignore[arg-type]
    for f, d in session.execute(
        select(DocFile, Document).join(Document, Document.id == DocFile.document_id)
    ).all():
        out.append(("документы", f.file_id, doc_title(d.kind, d.number)))
    return out
