"""Связь планировки и учёта (5.5): предмет на плане и инвентарная единица — отдельно, но
могут быть связаны (одна единица — не больше одного предмета).

- связанный предмет перенесли на плане в другое помещение — проводится «Перемещение» от
  имени того, кто перенёс (С13); внутри помещения — только расстановка;
- единицу переместили документом или списали — её предмет уходит с плана, а в новом
  помещении единица — в «Неразмещённых» (С12, С15);
- выбранные предметы ставятся на учёт «Вводом остатков» или «Приходом» и связываются с
  новыми единицами (С10);
- предметы количественного учёта поштучно не связываются — сверяется их число с остатком.
"""

import datetime as dt
import uuid
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.inventory import api as inventory
from app.modules.planning import api as planning

BASIS_MOVED = "Перенос на плане"
BASIS_WALK = "Постановка на учёт с плана"


def _room_place(item: Any) -> str | None:
    return inventory.room_key(item.room_id) if item.room_id else None


# ---------------------------------------------------------------- подписчики


def items_changed(
    session: Session, actor: Actor, touched: list[Any], _deleted: list[Any]
) -> list[str]:
    """Расстановка изменилась: связанные предметы в другом помещении — перемещение (С13)."""
    linked = [i for i in touched if i.unit_id]
    if not linked:
        return []
    units = inventory.units_by_id(session, [i.unit_id for i in linked])
    types = catalog.types_by_id(session, [i.type_id for i in linked])
    moves: dict[str, list[Any]] = {}
    for item in linked:
        unit = units.get(item.unit_id)
        if unit is None or unit.state == "written_off":
            raise Conflict(
                "Инвентарная единица не найдена или списана — связать с ней предмет нельзя."
            )
        name = types[item.type_id].name
        if unit.type_id != item.type_id:
            raise AppError(f"Единица {unit.number} — другого типа, не «{name}».")
        to = _room_place(item)
        if to is None:
            raise AppError(
                f"«{name}» № {unit.number} числится в учёте — ставьте его в помещение, "
                "а не вне помещений."
            )
        if unit.place != to and unit.parent_id is None:
            moves.setdefault(to, []).append(unit)
    notes = []
    for to, moved in moves.items():
        sources = {u.place for u in moved}
        doc = inventory.post_document(
            session,
            actor,
            "transfer",
            {
                "to_place": to,
                "from_place": next(iter(sources)) if len(sources) == 1 else None,
                "basis": BASIS_MOVED,
            },
            [{"unit_id": u.id} for u in moved],
        )
        notes.append(f"Оформлено «{inventory.doc_brief(doc)['title']}»: единиц {len(moved)}.")
    return notes


def plan_saved(session: Session, actor: Actor, floor_id: uuid.UUID) -> None:
    """План сохранили, помещения поменяли очертания — предметы пересчитаны по точкам (5.1.6);
    связанные, оказавшиеся в другом помещении, — перемещение в учёте с основанием «Изменение
    плана». Объединение помещений учёт переносит сам."""
    linked = [i for i in planning.floor_items_raw(session, floor_id) if i.unit_id and i.room_id]
    units = inventory.units_by_id(session, [i.unit_id for i in linked])
    moves: dict[str, list[Any]] = {}
    for item in linked:
        unit = units.get(item.unit_id)
        to = _room_place(item)
        if unit is None or unit.state == "written_off" or unit.parent_id or unit.place == to:
            continue
        moves.setdefault(to, []).append(unit)  # type: ignore[arg-type]
    for to, moved in moves.items():
        inventory.post_document(
            session,
            actor,
            "transfer",
            {"to_place": to, "basis": "Изменение плана"},
            [{"unit_id": u.id} for u in moved],
        )


def units_changed(session: Session, actor: Actor, units: list[Any]) -> None:
    """Документ переместил или списал единицы: их предметы, что стоят не там, уходят с плана
    (история остаётся в журнале расстановки)."""
    by_id = {u.id: u for u in units}
    items = planning.items_of_units(session, list(by_id))
    gone = []
    for unit_id, item in items.items():
        unit = by_id[unit_id]
        if unit.state == "written_off" or unit.place != _room_place(item):
            gone.append(item)
    if gone:
        planning.remove_items(session, actor, gone)


# ------------------------------------------------- этаж: единицы, неразмещённые, сверка


def floor_view(session: Session, actor: Actor, floor_id: uuid.UUID) -> dict[str, Any]:
    floor = building.get_floor(session, actor, floor_id)
    items = planning.floor_items_raw(session, floor.id)
    on_plan = {i.unit_id: i.id for i in items if i.unit_id}
    units = inventory.floor_units(session, actor, floor.id)
    known = {u.id for u in units}
    units += inventory.units_by_id(session, [u for u in on_plan if u not in known]).values()
    briefs = inventory.unit_briefs(session, actor, units)
    types = catalog.types_by_id(
        session, list({b["type_id"] for b in briefs} | {i.type_id for i in items})
    )
    rooms = {r.id: building.room_title(r) for r in building.live_rooms(session, floor.id)}
    out_units = []
    for b in briefs:
        t = types[b["type_id"]]
        b["item_id"] = on_plan.get(b["id"])
        b["room_title"] = rooms.get(uuid.UUID(b["room_id"])) if b["room_id"] else ""
        b["placeable"] = t.layer_id is not None and t.archived_at is None
        out_units.append(b)
    # сверка количественного учёта: «на плане 8 светильников, по учёту 6»
    stock = inventory.room_stock(session, floor.id)
    counted: Counter[tuple[str, uuid.UUID]] = Counter(
        (inventory.room_key(i.room_id), i.type_id)
        for i in items
        if i.room_id and types[i.type_id].accounting == "quantity"
    )
    stock_types = catalog.types_by_id(session, [t for _, t in stock])
    mismatch = []
    for key in sorted(
        set(counted) | set(stock), key=lambda k: (rooms.get(uuid.UUID(k[0][2:]), ""), k[1].hex)
    ):
        place, type_id = key
        t = types.get(type_id) or stock_types.get(type_id)
        if t is None or t.layer_id is None:
            continue
        have = stock.get(key, Decimal(0))
        if Decimal(counted.get(key, 0)) != have:
            mismatch.append(
                {
                    "room_id": place[2:],
                    "room_title": rooms.get(uuid.UUID(place[2:]), ""),
                    "type_id": type_id,
                    "type_name": t.name,
                    "unit": t.unit,
                    "on_plan": counted.get(key, 0),
                    "in_stock": float(have),
                }
            )
    return {
        "units": out_units,
        "unplaced": [b["id"] for b in out_units if b["item_id"] is None and b["placeable"]],
        "mismatch": mismatch,
    }


def unit_item(session: Session, actor: Actor, unit_id: uuid.UUID) -> dict[str, Any] | None:
    """Где на плане стоит единица (для «Показать на плане»)."""
    item = planning.items_of_units(session, [unit_id]).get(unit_id)
    if item is None:
        return None
    item = planning.get_item(session, actor, item.id)
    return {"item_id": item.id, "floor_id": item.floor_id, "building_id": item.building_id}


# ------------------------------------------------- постановка на учёт с плана (С10)


@dataclass
class Register:
    floor_id: uuid.UUID
    item_ids: list[uuid.UUID]
    kind: str = "opening"
    date: dt.date | None = None
    supplier: str = ""
    basis: str = ""
    responsible: str = ""
    department: str = ""
    # цена по типу или «тип/модель»; нет — цена модели, тип, иначе 0
    prices: dict[str, float] = field(default_factory=dict)


def register(session: Session, actor: Actor, r: Register) -> dict[str, Any]:
    if not actor.is_admin:
        raise Forbidden()
    if r.kind not in ("opening", "receipt"):
        raise AppError("Поставить на учёт можно «Вводом остатков» или «Приходом».", field="kind")
    floor = building.get_floor(session, actor, r.floor_id)
    found = planning.items_by_id(session, r.item_ids)
    items = [found[i] for i in r.item_ids if i in found]
    if not items:
        raise AppError("Выберите предметы на плане.")
    types = catalog.types_by_id(session, [i.type_id for i in items])
    models = catalog.models_by_id(session, [i.model_id for i in items if i.model_id])
    for item in items:
        name = types[item.type_id].name
        if item.floor_id != floor.id:
            raise AppError("Предметы — с другого этажа.")
        if item.unit_id:
            raise Conflict(f"«{name}» уже стоит на учёте.", code="linked")
        if item.room_id is None:
            raise AppError(f"«{name}» стоит вне помещений — поставьте его в помещение.")

    def price(item: Any) -> Any:
        key = f"{item.type_id}/{item.model_id}" if item.model_id else str(item.type_id)
        if key in r.prices:
            return r.prices[key]
        if str(item.type_id) in r.prices:
            return r.prices[str(item.type_id)]
        m = models.get(item.model_id) if item.model_id else None
        return (m.price if m and m.price is not None else types[item.type_id].price) or 0

    common = {"responsible": r.responsible, "department": r.department}
    lines: list[dict[str, Any]] = []
    linked: list[Any] = []  # предмет на строку — для поштучных
    grouped: dict[tuple[str, uuid.UUID], list[Any]] = {}
    for item in items:
        if types[item.type_id].accounting == "quantity":
            grouped.setdefault((_room_place(item), item.type_id), []).append(item)  # type: ignore[arg-type]
            continue
        lines.append(
            {
                "type_id": item.type_id,
                "model_id": item.model_id,
                "qty": 1,
                "price": price(item),
                "to_place": _room_place(item),
                **common,
            }
        )
        linked.append(item)
    # количественный учёт: остатком — только недостающее до числа на плане, чтобы второй
    # раз не оприходовать то же самое
    stock_lines: list[dict[str, Any]] = []
    if grouped:
        stock = inventory.room_stock(session, floor.id)
        on_plan = Counter(
            (_room_place(i), i.type_id)
            for i in planning.floor_items_raw(session, floor.id)
            if i.room_id and i.type_id in {k[1] for k in grouped}
        )
        rooms = {r.id: building.room_title(r) for r in building.live_rooms(session, floor.id)}
        for (place, type_id), rows in grouped.items():
            need = on_plan[(place, type_id)] - int(stock.get((place, type_id), Decimal(0)))
            qty = min(len(rows), need)
            if qty <= 0:
                continue
            t = types[type_id]
            lines.append(
                {
                    "type_id": type_id,
                    "model_id": rows[0].model_id,
                    "qty": qty,
                    "price": price(rows[0]),
                    "to_place": place,
                }
            )
            stock_lines.append(
                {
                    "type_name": t.name,
                    "qty": qty,
                    "unit": t.unit,
                    "room_title": rooms.get(uuid.UUID(place[2:]), ""),
                }
            )
    if not lines:
        raise Conflict(
            "Всё выбранное уже на учёте: количественный учёт сходится с числом на плане.",
            code="linked",
        )
    header: dict[str, Any] = {
        "basis": r.basis or BASIS_WALK,
        "supplier": r.supplier,
    }
    if r.date:
        header["date"] = r.date
    doc = inventory.post_document(session, actor, r.kind, header, lines)
    created = inventory.created_units(session, doc)
    unit_ids = []
    for item, units in zip(linked, created, strict=False):
        planning.link_unit(session, item, units[0].id)
        unit_ids.append(units[0].id)
    session.flush()
    return {
        "document": inventory.doc_brief(doc),
        "unit_ids": unit_ids,
        "items": [planning.item_view(i) for i in linked],
        "stock": stock_lines,
    }


# ---------------------------------------------------------------- убрать связанный предмет


def remove(
    session: Session,
    actor: Actor,
    item_ids: list[uuid.UUID],
    mode: str,
    to_place: str | None,
    reason: str,
) -> dict[str, Any]:
    """Связанный предмет убирают с плана: вернуть единицу на склад (перемещение) или списать.
    Предмет уходит с плана сам — вслед за документом."""
    if not actor.is_admin:
        raise Forbidden()
    found = planning.items_by_id(session, item_ids)
    linked = [found[i] for i in item_ids if i in found and found[i].unit_id]
    if not linked:
        raise NotFound("Связанных предметов среди выбранных нет.")
    for item in linked:
        planning.get_item(session, actor, item.id)
    units = inventory.units_by_id(session, [i.unit_id for i in linked])
    ids = set(units)
    # входящее в состав другой единицы уходит вместе с ней
    rows = [u for u in units.values() if not (u.parent_id and u.parent_id in ids)]
    if mode == "return":
        if not to_place:
            raise AppError("Выберите, куда вернуть.", field="to_place")
        doc = inventory.post_document(
            session,
            actor,
            "transfer",
            {"to_place": to_place, "basis": "Возврат с плана"},
            [{"unit_id": u.id} for u in rows],
        )
    elif mode == "writeoff":
        if not reason.strip():
            raise AppError("Укажите причину списания.", field="reason")
        doc = inventory.post_document(
            session,
            actor,
            "writeoff",
            {"reason": reason.strip()},
            [{"unit_id": u.id} for u in rows],
        )
    else:
        raise AppError("Вернуть на склад или списать.", field="mode")
    still = planning.items_by_id(session, [i.id for i in linked])
    return {
        "document": inventory.doc_brief(doc),
        "deleted": [str(i.id) for i in linked if i.id not in still],
    }
