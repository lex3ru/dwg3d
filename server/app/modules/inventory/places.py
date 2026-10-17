"""Места хранения (5.4.1): помещения здания сами по себе и склады с ячейками."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound, stale
from app.modules.building import api as building
from app.modules.inventory.models import Cell, StockMove, Unit, Warehouse
from app.modules.journal import api as journal

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def label_code() -> str:
    """Код QR-метки: постоянный, без данных о вещи (5.4.7)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(12))


def admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden()


@dataclass
class Place:
    key: str
    kind: str  # room warehouse cell
    title: str  # «2 этаж › 214 Кабинет», «Склад «Основной» › Стеллаж 1»
    short: str  # «214 Кабинет», «Склад «Основной»»
    building_id: uuid.UUID | None
    floor_id: uuid.UUID | None
    room_id: uuid.UUID | None
    warehouse_id: uuid.UUID | None

    def view(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "title": self.title,
            "short": self.short,
            "building_id": self.building_id,
            "floor_id": self.floor_id,
            "room_id": self.room_id,
            "warehouse_id": self.warehouse_id,
        }


def room_key(room_id: uuid.UUID) -> str:
    return f"r:{room_id}"


class Places:
    """Разбор ключей мест с запоминанием — на один запрос."""

    def __init__(self, session: Session, actor: Actor):
        self.session = session
        self.actor = actor
        self._cache: dict[str, Place] = {}
        self._floors: dict[uuid.UUID, str] = {}

    def _floor_name(self, floor_id: uuid.UUID) -> str:
        if floor_id not in self._floors:
            self._floors[floor_id] = building.get_floor(self.session, self.actor, floor_id).name
        return self._floors[floor_id]

    def _room(self, room_id: uuid.UUID) -> Place:
        room = building.get_room(self.session, self.actor, room_id)
        return self._room_place(room, self._floor_name(room.floor_id))

    @staticmethod
    def _room_place(room: Any, floor_name: str) -> Place:
        title = building.room_title(room)
        return Place(
            room_key(room.id),
            "room",
            f"{floor_name} › {title}",
            title,
            room.building_id,
            room.floor_id,
            room.id,
            None,
        )

    def preload(self, keys: Any) -> None:
        """Помещения среди ключей — одним запросом, а не по одному (8.1)."""
        ids = []
        for key in {k for k in keys if k and k.startswith("r:") and k not in self._cache}:
            try:
                ids.append(uuid.UUID(key[2:]))
            except ValueError:
                continue
        for room, floor_name in building.rooms_with_floor(self.session, self.actor, ids):
            self._cache[room_key(room.id)] = self._room_place(room, floor_name)

    def get(self, key: str | None) -> Place:
        if not key:
            raise AppError("Не указано место хранения.", field="place")
        if key in self._cache:
            return self._cache[key]
        kind, _, raw = key.partition(":")
        try:
            ident = uuid.UUID(raw)
        except ValueError:
            raise AppError("Неверное место хранения.", field="place") from None
        if kind == "r":
            place = self._room(ident)
        elif kind in ("w", "c"):
            cell = self.session.get(Cell, ident) if kind == "c" else None
            if kind == "c" and cell is None:
                raise NotFound("Ячейка склада не найдена.")
            wh = self.session.get(Warehouse, cell.warehouse_id if cell else ident)
            if wh is None:
                raise NotFound("Склад не найден.")
            if wh.building_id and not self.actor.can_see_building(wh.building_id):
                raise NotFound("Склад не найден.")
            if not wh.building_id and not self.actor.is_admin:
                raise NotFound("Склад не найден.")
            floor_id = None
            if wh.room_id:
                floor_id = building.get_room(self.session, self.actor, wh.room_id).floor_id
            name = f"Склад «{wh.name}»"
            place = Place(
                key,
                "cell" if cell else "warehouse",
                f"{name} › {cell.name}" if cell else name,
                f"{name} › {cell.name}" if cell else name,
                wh.building_id,
                floor_id,
                wh.room_id,
                wh.id,
            )
        else:
            raise AppError("Неверное место хранения.", field="place")
        self._cache[key] = place
        return place

    def title(self, key: str | None) -> str:
        if not key:
            return ""
        try:
            return self.get(key).title
        except (NotFound, AppError):
            return "место недоступно"


def is_storage(place: Place) -> bool:
    return place.kind in ("warehouse", "cell")


# ---------------------------------------------------------------- склады


def warehouse_view(session: Session, wh: Warehouse) -> dict[str, Any]:
    cells = list(
        session.scalars(
            select(Cell)
            .where(Cell.warehouse_id == wh.id, Cell.archived_at.is_(None))
            .order_by(Cell.position, Cell.name)
        )
    )
    return {
        "id": wh.id,
        "key": f"w:{wh.id}",
        "name": wh.name,
        "building_id": wh.building_id,
        "room_id": wh.room_id,
        "note": wh.note,
        "label_code": wh.label_code,
        "archived": wh.archived_at is not None,
        "cells": [
            {"id": c.id, "key": f"c:{c.id}", "name": c.name, "label_code": c.label_code}
            for c in cells
        ],
        "version": wh.version,
    }


def warehouses(session: Session, actor: Actor, archived: bool = False) -> list[Warehouse]:
    q = select(Warehouse).order_by(Warehouse.name)
    if not archived:
        q = q.where(Warehouse.archived_at.is_(None))
    return [
        w
        for w in session.scalars(q)
        if (w.building_id and actor.can_see_building(w.building_id)) or actor.is_admin
    ]


def _warehouse_fields(session: Session, actor: Actor, v: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "name" in v:
        name = str(v["name"] or "").strip()
        if not name:
            raise AppError("Укажите название склада.", field="name")
        out["name"] = name[:150]
    if "room_id" in v:
        room_id = v["room_id"] or None
        if room_id:
            room = building.get_room(session, actor, uuid.UUID(str(room_id)))
            out["room_id"], out["building_id"] = room.id, room.building_id
        else:
            out["room_id"] = None
    if "building_id" in v and "room_id" not in out:
        bid = v["building_id"] or None
        out["building_id"] = (
            building.get_building(session, actor, uuid.UUID(str(bid))).id if bid else None
        )
    if "note" in v:
        out["note"] = str(v["note"] or "")[:300]
    return out


def create_warehouse(session: Session, actor: Actor, v: dict[str, Any]) -> Warehouse:
    admin(actor)
    fields = _warehouse_fields(session, actor, v)
    if "name" not in fields:
        raise AppError("Укажите название склада.", field="name")
    wh = Warehouse(id=uuid.uuid4(), label_code=label_code(), version=1, note="", **fields)
    session.add(wh)
    session.flush()
    journal.record(
        session,
        actor,
        "inventory.warehouse_create",
        f"Заведён склад «{wh.name}»",
        entity=f"warehouse:{wh.id}",
    )
    return wh


def get_warehouse(session: Session, actor: Actor, wh_id: uuid.UUID) -> Warehouse:
    wh = session.get(Warehouse, wh_id)
    if wh is None or not (
        actor.is_admin or (wh.building_id and actor.can_see_building(wh.building_id))
    ):
        raise NotFound("Склад не найден.")
    return wh


def update_warehouse(
    session: Session, actor: Actor, wh_id: uuid.UUID, v: dict[str, Any]
) -> Warehouse:
    admin(actor)
    wh = get_warehouse(session, actor, wh_id)
    if v.get("version") is not None and int(v["version"]) != wh.version:
        raise stale("Склад")
    fields = _warehouse_fields(session, actor, v)
    for k, value in fields.items():
        setattr(wh, k, value)
    if "archived" in v:
        if v["archived"] and _holds(
            session, f"w:{wh.id}", [f"c:{c.id}" for c in _cells(session, wh)]
        ):
            raise Conflict("На складе числится имущество — сначала переместите его.")
        wh.archived_at = datetime.now(UTC) if v["archived"] else None
    wh.version += 1
    journal.record(
        session,
        actor,
        "inventory.warehouse_update",
        f"Изменён склад «{wh.name}»",
        entity=f"warehouse:{wh.id}",
    )
    return wh


def _cells(session: Session, wh: Warehouse) -> list[Cell]:
    return list(session.scalars(select(Cell).where(Cell.warehouse_id == wh.id)))


def _holds(session: Session, *keys_or_lists: Any) -> bool:
    keys: list[str] = []
    for k in keys_or_lists:
        keys.extend(k if isinstance(k, list) else [k])
    units = session.scalar(
        select(func.count())
        .select_from(Unit)
        .where(Unit.place.in_(keys), Unit.state != "written_off")
    )
    if units:
        return True
    rest = session.execute(
        select(StockMove.type_id, func.sum(StockMove.qty))
        .where(StockMove.place.in_(keys))
        .group_by(StockMove.type_id, StockMove.model_id)
    ).all()
    return any(q and q > 0 for _, q in rest)


def add_cell(session: Session, actor: Actor, wh_id: uuid.UUID, name: str) -> Cell:
    admin(actor)
    wh = get_warehouse(session, actor, wh_id)
    name = (name or "").strip()
    if not name:
        raise AppError("Укажите ячейку: стеллаж, полку.", field="name")
    position = (
        session.scalar(select(func.max(Cell.position)).where(Cell.warehouse_id == wh.id)) or 0
    ) + 1
    cell = Cell(
        id=uuid.uuid4(),
        warehouse_id=wh.id,
        name=name[:100],
        position=position,
        label_code=label_code(),
    )
    session.add(cell)
    session.flush()
    journal.record(
        session,
        actor,
        "inventory.cell_create",
        f"Склад «{wh.name}»: ячейка «{cell.name}»",
        entity=f"warehouse:{wh.id}",
    )
    return cell


def remove_cell(session: Session, actor: Actor, cell_id: uuid.UUID) -> None:
    admin(actor)
    cell = session.get(Cell, cell_id)
    if cell is None:
        raise NotFound("Ячейка не найдена.")
    if _holds(session, f"c:{cell.id}"):
        raise Conflict("В ячейке числится имущество — сначала переместите его.")
    cell.archived_at = datetime.now(UTC)
    journal.record(
        session,
        actor,
        "inventory.cell_archive",
        f"Убрана ячейка «{cell.name}»",
        entity=f"warehouse:{cell.warehouse_id}",
    )
