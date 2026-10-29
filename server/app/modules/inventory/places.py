"""Места хранения (5.4.1): помещения здания сами по себе и склады с ячейками."""

import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, String, and_, case, cast, func, literal, select, true
from sqlalchemy.orm import Session, aliased

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

    def refs(self, keys: Iterable[str | None]) -> list[str]:
        """Ссылки записи журнала на места, их этажи и здания: по ним запись найдётся в лентах
        помещения, склада, этажа и здания (5.7.3, R-041) и дойдёт до «просмотра» здания
        (R-012). Недоступное место — без ссылок."""
        wanted = [k for k in dict.fromkeys(keys) if k]
        self.preload(wanted)
        out: list[str] = []
        for key in wanted:
            try:
                place = self.get(key)
            except (NotFound, AppError):
                continue
            if place.kind == "room":
                out.append(f"room:{place.room_id}")
            if place.warehouse_id:
                out.append(f"warehouse:{place.warehouse_id}")
            if place.floor_id:
                out.append(f"floor:{place.floor_id}")
            if place.building_id:
                out.append(f"building:{place.building_id}")
        return list(dict.fromkeys(out))


def title_sql(q: Select[Any], actor: Actor, key: Any) -> tuple[Select[Any], Any]:
    """Places.title в базе — для сортировки реестра по месту без подписей 8 000 мест в Python
    (8.1, R-036, ADR-0018): q с присоединёнными помещениями, складами и ячейками и выражение
    подписи столбца key. Подписи и видимость — как у Places.get."""
    rooms = building.room_titles()
    wh, cell, cell_wh = aliased(Warehouse), aliased(Cell), aliased(Warehouse)

    def seen(building_id: Any) -> Any:
        return true() if actor.is_admin else building_id.in_(list(actor.building_ids))

    q = (
        q.outerjoin(rooms, literal("r:") + cast(rooms.c.id, String) == key)
        .outerjoin(wh, literal("w:") + cast(wh.id, String) == key)
        .outerjoin(cell, literal("c:") + cast(cell.id, String) == key)
        .outerjoin(cell_wh, cell_wh.id == cell.warehouse_id)
    )
    title = func.coalesce(
        case((and_(rooms.c.id.is_not(None), seen(rooms.c.building_id)),
              rooms.c.floor_name + " › " + rooms.c.title)),
        case((and_(wh.id.is_not(None), seen(wh.building_id)), "Склад «" + wh.name + "»")),
        case((and_(cell_wh.id.is_not(None), seen(cell_wh.building_id)),
              "Склад «" + cell_wh.name + "» › " + cell.name)),
        "место недоступно",
    )
    return q, title


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
    wh = Warehouse(id=uuid.uuid4(), label_code=label_code(), version=1, **{"note": "", **fields})
    session.add(wh)
    session.flush()
    journal.record(
        session,
        actor,
        "inventory.warehouse_create",
        f"Заведён склад «{wh.name}»",
        entity=f"warehouse:{wh.id}",
        refs=Places(session, actor).refs([f"w:{wh.id}"]),
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
    was = Places(session, actor).refs([f"w:{wh.id}"])  # склад могли перенести в другое здание
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
        refs=[*was, *Places(session, actor).refs([f"w:{wh.id}"])],
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


def room_property(session: Session, room_ids: list[uuid.UUID]
                  ) -> dict[uuid.UUID, dict[str, int]]:
    """Что числится в помещениях (5.1.6 п. 3, R-023): единиц (кроме списанных) и позиций
    остатков с количеством больше нуля — только помещения, где что-то есть."""
    keys = {room_key(rid): rid for rid in room_ids}
    out: dict[uuid.UUID, dict[str, int]] = {}
    units = session.execute(
        select(Unit.place, func.count())
        .where(Unit.place.in_(list(keys)), Unit.state != "written_off")
        .group_by(Unit.place)
    )
    for place, n in units:
        out.setdefault(keys[place], {"units": 0, "stock": 0})["units"] = n
    stock = session.execute(
        select(StockMove.place, func.sum(StockMove.qty))
        .where(StockMove.place.in_(list(keys)))
        .group_by(StockMove.place, StockMove.type_id, StockMove.model_id)
    )
    for place, qty in stock:
        if qty and qty > 0:
            out.setdefault(keys[place], {"units": 0, "stock": 0})["stock"] += 1
    return out


def places_check(session: Session) -> dict[str, Any]:
    """Страница состояния (8.5 п. 4, R-028): у места нет внешнего ключа — сколько единиц и
    позиций остатков числится в убранных или несуществующих местах. Их не найти на плане и не
    видит ведомость помещения."""
    units = dict(
        session.execute(
            select(Unit.place, func.count())
            .where(Unit.state != "written_off")
            .group_by(Unit.place)
        ).all()
    )
    stock: dict[str, int] = {}
    for place, qty in session.execute(
        select(StockMove.place, func.sum(StockMove.qty)).group_by(
            StockMove.place, StockMove.type_id, StockMove.model_id
        )
    ):
        if qty and qty > 0:
            stock[place] = stock.get(place, 0) + 1
    gone = _gone(session, {*units, *stock})
    if not gone:
        return {"name": "Места учёта", "ok": True,
                "detail": "всё числится в действующих помещениях и на складах"}
    return {
        "name": "Места учёта",
        "ok": False,
        "detail": f"в убранных или несуществующих местах — единиц: "
        f"{sum(units.get(k, 0) for k in gone)}, позиций остатков: "
        f"{sum(stock.get(k, 0) for k in gone)}. Перенесите их документом; убранные помещения "
        "этажа показывает ведомость инвентаризации этажа.",
    }


def _gone(session: Session, keys: set[str]) -> set[str]:
    """Места, которых нет или которые убраны (помещение, склад, ячейка)."""
    ids: dict[str, dict[uuid.UUID, str]] = {"r": {}, "w": {}, "c": {}}
    gone: set[str] = set()
    for key in keys:
        kind, _, raw = key.partition(":")
        try:
            ids[kind][uuid.UUID(raw)] = key
        except (KeyError, ValueError):
            gone.add(key)
    live = building.live_room_ids(session, ids["r"])
    live.update(session.scalars(select(Warehouse.id).where(
        Warehouse.id.in_(list(ids["w"])), Warehouse.archived_at.is_(None))))
    live.update(session.scalars(
        select(Cell.id)
        .join(Warehouse, Warehouse.id == Cell.warehouse_id)
        .where(Cell.id.in_(list(ids["c"])), Cell.archived_at.is_(None),
               Warehouse.archived_at.is_(None))
    ))
    for of_kind in ids.values():
        gone.update(key for ident, key in of_kind.items() if ident not in live)
    return gone


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
        refs=Places(session, actor).refs([f"w:{wh.id}"]),
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
        refs=Places(session, actor).refs([f"w:{cell.warehouse_id}"]),
    )
