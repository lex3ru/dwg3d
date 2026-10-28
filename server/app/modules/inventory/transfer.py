"""Перенос здания на другую установку: учёт в его текущем состоянии — склады здания с
ячейками, метки на дверях, инвентарные единицы (номер, тип и модель, серийный номер, место,
состояние, ответственный, подразделение, примечание, характеристики, цена, дата ввода, срок
службы, переоценка, вложение, фото и файлы, код QR-метки) и остатки количественного учёта.
На новой установке всё ставится на учёт одним «Вводом остатков» (движение — только
документами, 5.4.4); история документов не переносится. Коды QR-меток сохраняются, если на
новой установке они свободны: наклейки остаются верными, если адрес системы прежний."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError
from app.modules.building import api as building
from app.modules.inventory import documents, places
from app.modules.inventory.models import Cell, RoomLabel, StockMove, Unit, UnitFile, Warehouse
from app.modules.journal import api as journal

UNIT_FIELDS = ("number", "serial", "state", "responsible", "department", "note", "life_months")


def _keys(session: Session, building_id: uuid.UUID) -> tuple[list[Warehouse], set[str]]:
    whs = list(
        session.scalars(
            select(Warehouse).where(
                Warehouse.building_id == building_id, Warehouse.archived_at.is_(None)
            )
        )
    )
    keys = {f"r:{r}" for r in building.room_ids_of(session, building_id)}
    keys |= {f"w:{w.id}" for w in whs}
    keys |= {
        f"c:{c}"
        for c in session.scalars(select(Cell.id).where(Cell.warehouse_id.in_([w.id for w in whs])))
    }
    return whs, keys


def export(
    session: Session, actor: Actor, building_id: uuid.UUID
) -> tuple[dict[str, Any], list[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    """Учёт здания для пакета, id файлов, типов и моделей, которые ему нужны."""
    places.admin(actor)
    whs, keys = _keys(session, building_id)
    warehouses = [
        {
            "key": str(w.id),
            "name": w.name,
            "room": str(w.room_id) if w.room_id else None,
            "note": w.note,
            "label_code": w.label_code,
            "cells": [
                {"key": str(c.id), "name": c.name, "label_code": c.label_code}
                for c in session.scalars(
                    select(Cell)
                    .where(Cell.warehouse_id == w.id, Cell.archived_at.is_(None))
                    .order_by(Cell.position)
                )
            ],
        }
        for w in whs
    ]
    room_ids = building.room_ids_of(session, building_id)
    door_labels = {
        str(r.room_id): r.label_code
        for r in session.scalars(select(RoomLabel).where(RoomLabel.room_id.in_(room_ids)))
    }
    units = list(
        session.scalars(
            select(Unit)
            .where(Unit.state != "written_off", Unit.place.in_(keys))
            .order_by(Unit.number)
        )
    )
    files: list[uuid.UUID] = []
    unit_files: dict[uuid.UUID, list[dict[str, str]]] = defaultdict(list)
    for uf in session.scalars(select(UnitFile).where(UnitFile.unit_id.in_([u.id for u in units]))):
        unit_files[uf.unit_id].append({"file": str(uf.file_id), "kind": uf.kind})
        files.append(uf.file_id)
    out_units = []
    for u in units:
        if u.photo_file_id:
            files.append(u.photo_file_id)
        out_units.append(
            {
                "key": str(u.id),
                "type": str(u.type_id),
                "model": str(u.model_id) if u.model_id else None,
                **{f: getattr(u, f) for f in UNIT_FIELDS},
                "place": u.place,
                "values": u.values or {},
                "price": float(u.price or 0),
                "commissioned_on": u.commissioned_on.isoformat(),
                "value_base": float(u.value_base) if u.value_base is not None else None,
                "value_date": u.value_date.isoformat() if u.value_date else None,
                "parent": str(u.parent_id) if u.parent_id else None,
                "label_code": u.label_code,
                "photo": str(u.photo_file_id) if u.photo_file_id else None,
                "files": unit_files.get(u.id, []),
            }
        )
    stock = [
        {
            "place": place,
            "type": str(t),
            "model": str(m) if m else None,
            "qty": float(qty),
            "amount": float(amount),
        }
        for place, t, m, qty, amount in session.execute(
            select(
                StockMove.place,
                StockMove.type_id,
                StockMove.model_id,
                func.sum(StockMove.qty),
                func.sum(StockMove.amount),
            )
            .where(StockMove.place.in_(keys))
            .group_by(StockMove.place, StockMove.type_id, StockMove.model_id)
        ).all()
        if qty and qty > 0
    ]
    type_ids = {u.type_id for u in units} | {uuid.UUID(s["type"]) for s in stock}
    model_ids = {u.model_id for u in units if u.model_id} | {
        uuid.UUID(s["model"]) for s in stock if s["model"]
    }
    return (
        {"warehouses": warehouses, "door_labels": door_labels, "units": out_units, "stock": stock},
        files,
        type_ids,
        model_ids,
    )


def check(session: Session, data: dict[str, Any]) -> dict[str, Any]:
    """Какие инвентарные номера пакета на новой установке уже заняты."""
    numbers = [u["number"] for u in data.get("units", []) if u.get("number")]
    taken: list[str] = []
    for i in range(0, len(numbers), 5000):
        taken += list(
            session.scalars(select(Unit.number).where(Unit.number.in_(numbers[i : i + 5000])))
        )
    return {
        "units": len(data.get("units", [])),
        "stock": len(data.get("stock", [])),
        "warehouses": len(data.get("warehouses", [])),
        "taken_numbers": sorted(taken),
    }


def _free(session: Session, cls: Any, code: str | None) -> bool:
    return (
        bool(code)
        and session.scalar(select(func.count()).select_from(cls).where(cls.label_code == code)) == 0
    )


def load(
    session: Session,
    actor: Actor,
    data: dict[str, Any],
    building_id: uuid.UUID,
    rooms: dict[str, uuid.UUID],
    types: dict[str, uuid.UUID | None],
    models: dict[str, uuid.UUID | None],
    item_chars: dict[tuple[str, str], str],
    files: dict[str, uuid.UUID],
    renumber: bool,
) -> dict[str, Any]:
    """Поставить учёт на новой установке. Возвращает соответствие ключей единиц новым id и
    итоги; номера, уже занятые на новой установке, с renumber выдаются заново, без — ошибка."""
    places.admin(actor)
    place_of: dict[str, str] = {f"r:{old}": f"r:{new}" for old, new in rooms.items()}
    for w in data.get("warehouses", []):
        wh = places.create_warehouse(
            session,
            actor,
            {
                "name": w["name"],
                "building_id": str(building_id),
                "note": w.get("note", ""),
                **({"room_id": str(rooms[w["room"]])} if w.get("room") in rooms else {}),
            },
        )
        if _free(session, Warehouse, w.get("label_code")):
            wh.label_code = w["label_code"]
        place_of[f"w:{w['key']}"] = f"w:{wh.id}"
        for c in w.get("cells", []):
            cell = places.add_cell(session, actor, wh.id, c["name"])
            if _free(session, Cell, c.get("label_code")):
                cell.label_code = c["label_code"]
            place_of[f"c:{c['key']}"] = f"c:{cell.id}"
    for old, code in data.get("door_labels", {}).items():
        if old in rooms and _free(session, RoomLabel, code):
            session.add(RoomLabel(room_id=rooms[old], label_code=code))
    session.flush()

    taken = set(check(session, data)["taken_numbers"])
    if taken and not renumber:
        raise AppError(
            f"Инвентарные номера уже заняты на этой установке: {', '.join(sorted(taken)[:10])}"
            + ("…" if len(taken) > 10 else "")
            + ". Загрузите с выдачей новых номеров.",
            code="numbers_taken",
        )
    lines: list[dict[str, Any]] = []
    keys: list[str | None] = []
    skipped = 0
    for u in data.get("units", []):
        type_id = types.get(u["type"])
        to = place_of.get(u["place"])
        if type_id is None or to is None:
            skipped += 1
            continue
        values = {
            item_chars[(u["type"], k)]: v
            for k, v in (u.get("values") or {}).items()
            if (u["type"], k) in item_chars
        }
        lines.append(
            {
                "type_id": type_id,
                "model_id": models.get(u["model"]) if u.get("model") else None,
                "qty": 1,
                "price": u.get("price", 0),
                **{f: u.get(f) for f in UNIT_FIELDS},
                "number": "" if u.get("number") in taken else u.get("number", ""),
                "commissioned_on": u.get("commissioned_on"),
                "values": values,
                "to_place": to,
            }
        )
        keys.append(u["key"])
    for s in data.get("stock", []):
        type_id = types.get(s["type"])
        to = place_of.get(s["place"])
        if type_id is None or to is None or not s.get("qty"):
            skipped += 1
            continue
        qty = Decimal(str(s["qty"]))
        lines.append(
            {
                "type_id": type_id,
                "model_id": models.get(s["model"]) if s.get("model") else None,
                "qty": qty,
                "price": (Decimal(str(s["amount"])) / qty).quantize(Decimal("0.01")),
                "to_place": to,
            }
        )
        keys.append(None)
    units: dict[str, uuid.UUID] = {}
    if not lines:
        return {"units": units, "document_id": None, "skipped": skipped, "renumbered": 0}
    doc = documents.new_draft(
        session, actor, "opening", {"basis": "Перенос здания с другой установки"}, lines
    )
    documents.post(session, actor, doc.id, doc.version)
    for line, key in zip(documents.lines_of(session, doc), keys, strict=True):
        if key and line.created_units:
            units[key] = uuid.UUID(line.created_units[0])

    # что «Ввод остатков» не задаёт: переоценка, вложение, фото и файлы, код метки
    source = {u["key"]: u for u in data.get("units", [])}
    loaded = {u.id: u for u in session.scalars(select(Unit).where(Unit.id.in_(units.values())))}
    for key, unit_id in units.items():
        u, unit = source[key], loaded[unit_id]
        if u.get("value_base") is not None and u.get("value_date"):
            unit.value_base = u["value_base"]
            unit.value_date = date.fromisoformat(u["value_date"])
        if u.get("parent") in units:
            unit.parent_id = units[u["parent"]]
        if u.get("photo") and files.get(u["photo"]):
            unit.photo_file_id = files[u["photo"]]
        for f in u.get("files", []):
            if files.get(f["file"]):
                session.add(
                    UnitFile(
                        id=uuid.uuid4(),
                        unit_id=unit_id,
                        file_id=files[f["file"]],
                        kind=f.get("kind", "doc"),
                    )
                )
        if (
            u.get("label_code")
            and u["label_code"] != unit.label_code
            and _free(session, Unit, u["label_code"])
        ):
            unit.label_code = u["label_code"]
    session.flush()
    renumbered = sum(1 for u in data.get("units", []) if u.get("number") in taken)
    if renumbered:
        journal.record(
            session,
            actor,
            "inventory.transfer_renumber",
            f"Перенос здания: {renumbered} единиц получили новые номера — прежние "
            "уже заняты на этой установке",
            entity=f"document:{doc.id}",
            refs=places.Places(session, actor).refs(sorted(documents.doc_places(session, doc))),
        )
    return {"units": units, "document_id": doc.id, "skipped": skipped, "renumbered": renumbered}
