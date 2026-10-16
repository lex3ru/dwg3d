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
from app.modules.inventory.models import Cell, StockMove, Unit, UnitEvent, Warehouse
from app.modules.inventory.places import Places, room_key
from app.modules.inventory.units import visible
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
    raise NotFound("Метка не найдена — или эта вещь вам недоступна.")
