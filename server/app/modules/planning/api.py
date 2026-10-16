"""Расстановка (5.3.2): предметы на плане этажа.

Расстановка сохраняется каждым действием (6.5.2): действие редактора — одна пачка изменений
(поставить, передвинуть, убрать), применяется целиком в одной транзакции и одной записью
журнала. Отмена в редакторе — такая же пачка с обратными изменениями; поэтому предмет можно
поставить заново с тем же ключом.
"""

import math
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from shapely import Point, Polygon, prepare
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound, stale
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.journal import api as journal
from app.modules.planning.models import Item

LIMIT = 20_000  # мм: координата дальше 20 км от начала плана — ошибка ввода
FIELDS = ("x", "y", "angle", "z", "parent_id", "label", "model_id")


def item_view(item: Item) -> dict[str, Any]:
    return {
        "id": item.id,
        "floor_id": item.floor_id,
        "room_id": item.room_id,
        "type_id": item.type_id,
        "model_id": item.model_id,
        "parent_id": item.parent_id,
        "x": item.x,
        "y": item.y,
        "angle": item.angle,
        "z": item.z,
        "label": item.label,
        "version": item.version,
    }


def floor_items(session: Session, actor: Actor, floor_id: uuid.UUID) -> list[Item]:
    floor = building.get_floor(session, actor, floor_id)
    return list(
        session.scalars(select(Item).where(Item.floor_id == floor.id).order_by(Item.created_at))
    )


def get_item(session: Session, actor: Actor, item_id: uuid.UUID) -> Item:
    item = session.get(Item, item_id)
    if item is None:
        raise NotFound("Предмет не найден.")
    building.get_floor(session, actor, item.floor_id)
    return item


# ---------------------------------------------------------------- в каком помещении


class Rooms:
    """Помещения этажа для поиска «в каком помещении точка»."""

    def __init__(self, session: Session, floor_id: uuid.UUID):
        self.shapes: list[tuple[uuid.UUID, Polygon]] = []
        for room in building.live_rooms(session, floor_id):
            if len(room.outline) >= 3:
                polygon = Polygon(room.outline)
                prepare(polygon)
                self.shapes.append((room.id, polygon))

    def at(self, x: float | None, y: float | None) -> uuid.UUID | None:
        if x is None or y is None:
            return None
        point = Point(x, y)
        return next((rid for rid, poly in self.shapes if poly.contains(point)), None)


def relocate(session: Session, floor_id: uuid.UUID) -> int:
    """Пересчитать помещения предметов этажа (план сохранён). Сколько предметов сменили
    помещение."""
    rooms = Rooms(session, floor_id)
    items = list(session.scalars(select(Item).where(Item.floor_id == floor_id)))
    by_id = {i.id: i for i in items}
    changed = 0
    for item in sorted(items, key=lambda i: i.parent_id is not None):
        parent = by_id.get(item.parent_id) if item.parent_id else None
        room = parent.room_id if parent else rooms.at(item.x, item.y)
        if room != item.room_id:
            item.room_id = room
            changed += 1
    return changed


# ---------------------------------------------------------------- пачка изменений


@dataclass
class Changes:
    create: list[dict[str, Any]] = field(default_factory=list)
    update: list[dict[str, Any]] = field(default_factory=list)
    delete: list[dict[str, Any]] = field(default_factory=list)


def _number(value: Any, what: str, low: float, high: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise AppError(f"{what}: нужно число.", field=what) from None
    if not math.isfinite(v) or v < low or v > high:
        raise AppError(f"{what}: вне допустимых пределов.", field=what)
    return v


def _uuid(value: Any, what: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise AppError(f"{what}: неверный ключ.", field=what) from None


def _placeable(session: Session, type_id: uuid.UUID) -> Any:
    t = catalog.get_type(session, type_id)
    if t.archived_at is not None:
        raise Conflict(f"Тип «{t.name}» в архиве — его нельзя поставить.", code="archived")
    # без слоя — расходные материалы: только учитываются. «Не ставится» со слоем (сервер,
    # коммутатор) — сам на план не ставится, но кладётся во вместилище (стойку 19″)
    if t.layer_id is None:
        raise AppError(f"Тип «{t.name}» не ставится на план — он только учитывается.")
    return t


def _model(session: Session, type_id: uuid.UUID, model_id: uuid.UUID | None) -> None:
    if model_id is None:
        return
    m = catalog.get_model(session, model_id)
    if m.type_id != type_id:
        raise AppError("Модель другого типа.", field="model_id")


class _Batch:
    def __init__(self, session: Session, actor: Actor, floor_id: uuid.UUID):
        self.session = session
        self.actor = actor
        self.floor = building.get_floor(session, actor, floor_id)
        self.rooms = Rooms(session, self.floor.id)
        self.items: dict[uuid.UUID, Item] = {
            i.id: i for i in session.scalars(select(Item).where(Item.floor_id == self.floor.id))
        }
        self.created: list[Item] = []
        self.updated: list[Item] = []
        self.deleted: list[Item] = []
        self.before: dict[uuid.UUID, dict[str, Any]] = {}
        self.type_names: dict[uuid.UUID, str] = {}

    def type_name(self, type_id: uuid.UUID) -> str:
        if type_id not in self.type_names:
            self.type_names[type_id] = catalog.get_type(self.session, type_id).name
        return self.type_names[type_id]

    def mine(self, value: Any, version: Any = None) -> Item:
        item_id = _uuid(value, "id")
        item = self.items.get(item_id) if item_id else None
        if item is None:
            raise NotFound("Предмет не найден — возможно, его уже убрали. Обновите страницу.")
        if version is not None and int(version) != item.version:
            raise stale("Предмет")
        return item

    def place(self, item: Item, values: dict[str, Any]) -> None:
        """Поля места: вложение или точка, поворот, высота, подпись."""
        if "parent_id" in values:
            parent_id = _uuid(values["parent_id"], "parent_id")
            if parent_id is not None:
                parent = self.items.get(parent_id)
                if parent is None:
                    raise AppError("Вместилище не найдено на этом этаже.", field="parent_id")
                if parent.id == item.id:
                    raise AppError("Предмет нельзя положить в него самого.", field="parent_id")
                if not catalog.get_type(self.session, parent.type_id).container:
                    raise AppError(
                        f"«{self.type_name(parent.type_id)}» не может содержать другие предметы.",
                        field="parent_id",
                    )
                if parent.parent_id is not None:
                    raise AppError("Вместилище само лежит в другом — вкладывать глубже нельзя.")
                if any(i.parent_id == item.id for i in self.items.values()):
                    raise AppError("В этом предмете лежат другие — его нельзя вложить.")
            item.parent_id = parent_id
        if item.parent_id is not None:
            item.x = item.y = None
        elif catalog.get_type(self.session, item.type_id).mount == "none":
            raise AppError(
                f"«{self.type_name(item.type_id)}» сам на план не ставится — только во "
                "вместилище (шкаф, стойку).",
                field="parent_id",
            )
        else:
            for k in ("x", "y"):
                if k in values:
                    setattr(item, k, _number(values[k], k, -LIMIT * 1000, LIMIT * 1000))
            if item.x is None or item.y is None:
                raise AppError("Укажите, где стоит предмет.", field="x")
        if "angle" in values:
            item.angle = _number(values["angle"], "angle", -1e6, 1e6) % 360
        if "z" in values:
            item.z = _number(values["z"], "z", -5000, 50_000)
        if "label" in values:
            label = str(values["label"] or "").strip()
            if len(label) > 100:
                raise AppError("Подпись — до 100 знаков.", field="label")
            item.label = label

    def locate(self, item: Item) -> None:
        parent = self.items.get(item.parent_id) if item.parent_id else None
        item.room_id = parent.room_id if parent else self.rooms.at(item.x, item.y)
        for child in self.items.values():
            if child.parent_id == item.id:
                child.room_id = item.room_id

    def create(self, values: dict[str, Any]) -> Item:
        item_id = _uuid(values.get("id"), "id") or uuid.uuid4()
        if item_id in self.items or self.session.get(Item, item_id) is not None:
            raise Conflict("Такой предмет уже есть.", code="exists")
        type_id = _uuid(values.get("type_id"), "type_id")
        if type_id is None:
            raise AppError("Укажите тип предмета.", field="type_id")
        t = _placeable(self.session, type_id)
        model_id = _uuid(values.get("model_id"), "model_id")
        _model(self.session, t.id, model_id)
        item = Item(
            id=item_id,
            building_id=self.floor.building_id,
            floor_id=self.floor.id,
            type_id=t.id,
            model_id=model_id,
            angle=0,
            z=0,
            label="",
            version=1,
        )
        self.type_names[t.id] = t.name
        self.items[item.id] = item
        self.place(item, {"z": _default_z(t, self.floor.height), **values})
        self.session.add(item)
        self.created.append(item)
        return item

    def update(self, values: dict[str, Any]) -> Item:
        item = self.mine(values.get("id"), values.get("version"))
        if item.id not in self.before:
            self.before[item.id] = _fields(item)
        changes = {k: v for k, v in values.items() if k in FIELDS}
        if "model_id" in changes:
            model_id = _uuid(changes["model_id"], "model_id")
            _model(self.session, item.type_id, model_id)
            item.model_id = model_id
        # вынуть из вместилища — поставить рядом с ним, если точку не дали
        if "parent_id" in changes and changes["parent_id"] in (None, "") and item.parent_id:
            parent = self.items[item.parent_id]
            changes.setdefault("x", parent.x)
            changes.setdefault("y", parent.y)
        self.place(item, changes)
        if item not in self.created and item not in self.updated:
            self.updated.append(item)
        return item

    def delete(self, values: dict[str, Any]) -> None:
        item = self.mine(values.get("id"), values.get("version"))
        self.before[item.id] = _fields(item)
        self.deleted.append(item)
        del self.items[item.id]


def _default_z(t: Any, floor_height: float) -> float:
    if t.mount == "wall":
        return float(t.mount_height or 1500)
    if t.mount == "ceiling":
        return float(t.mount_height or max(0.0, floor_height - (t.height or 0)))
    return 0.0


def _fields(item: Item) -> dict[str, Any]:
    out = {k: getattr(item, k) for k in FIELDS}
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in out.items()}


def _counted(names: list[str]) -> str:
    return ", ".join(f"{n} ×{c}" if c > 1 else n for n, c in Counter(names).items())


def apply_changes(
    session: Session, actor: Actor, floor_id: uuid.UUID, changes: Changes
) -> dict[str, Any]:
    if not actor.is_admin:
        raise Forbidden()
    if not (changes.create or changes.update or changes.delete):
        return {"items": [], "deleted": []}
    batch = _Batch(session, actor, floor_id)
    for values in changes.delete:
        batch.delete(values)
    # сначала то, что стоит само, потом вложенное (вместилище могло прийти в той же пачке)
    for values in sorted(changes.create, key=lambda v: v.get("parent_id") is not None):
        batch.create(values)
    for values in changes.update:
        batch.update(values)

    deleted_ids = {i.id for i in batch.deleted}
    taken_out: list[Item] = []
    for item in list(batch.deleted):
        for child in list(batch.items.values()):
            if child.parent_id != item.id or child.id in deleted_ids:
                continue
            if catalog.get_type(session, child.type_id).mount == "none":
                # само стоять не может (коммутатор из стойки) — уходит вместе с вместилищем
                batch.before[child.id] = _fields(child)
                batch.deleted.append(child)
                deleted_ids.add(child.id)
                del batch.items[child.id]
            else:
                # содержимое убранного вместилища остаётся на его месте
                child.parent_id, child.x, child.y = None, item.x, item.y
                taken_out.append(child)
    # сначала вложенное, потом вместилища: на них ссылаются
    for item in sorted(batch.deleted, key=lambda i: i.parent_id is None):
        session.delete(item)
        session.flush()

    now = datetime.now(UTC)
    touched = [*batch.created, *batch.updated, *taken_out]
    for item in touched:
        batch.locate(item)
        if item not in batch.created:
            item.version += 1
            item.updated_at = now
    session.flush()

    rooms_before = {i.room_id for i in batch.deleted}
    room_ids = {i.room_id for i in touched} | rooms_before
    room_titles = _room_titles(session, actor, room_ids)
    parts: list[str] = []
    if batch.created:
        parts.append("поставлены: " + _counted([batch.type_name(i.type_id) for i in batch.created]))
    moved = [*batch.updated, *taken_out]
    if moved:
        parts.append("изменены: " + _counted([batch.type_name(i.type_id) for i in moved]))
    if batch.deleted:
        parts.append("убраны: " + _counted([batch.type_name(i.type_id) for i in batch.deleted]))
    where = ", ".join(sorted(t for t in room_titles if t)) or "вне помещений"
    single = [*batch.created, *moved, *batch.deleted]
    entity = f"item:{single[0].id}" if len(single) == 1 else f"floor:{batch.floor.id}"
    before = {str(k): v for k, v in list(batch.before.items())[:20]}
    after = {str(i.id): _fields(i) for i in [*batch.created, *moved][:20]}
    journal.record(
        session,
        actor,
        "planning.change",
        f"Расстановка «{batch.floor.name}», {where}: " + "; ".join(parts),
        entity=entity,
        refs=[
            f"building:{batch.floor.building_id}",
            f"floor:{batch.floor.id}",
            *[f"room:{r}" for r in room_ids if r],
            *[f"item:{i.id}" for i in single],
        ],
        before=before or None,
        after=after or None,
    )
    return {"items": [item_view(i) for i in touched], "deleted": [str(i) for i in deleted_ids]}


def _room_titles(session: Session, actor: Actor, ids: set[uuid.UUID | None]) -> list[str]:
    out = []
    for rid in ids:
        if rid is None:
            continue
        out.append(building.room_title(building.get_room(session, actor, rid)))
    return out


# ---------------------------------------------------------------- связь с модулями ниже


def type_usage(session: Session, type_id: uuid.UUID | None, model_id: uuid.UUID | None) -> int:
    q = select(func.count()).select_from(Item)
    if type_id is not None:
        q = q.where(Item.type_id == type_id)
    if model_id is not None:
        q = q.where(Item.model_id == model_id)
    return session.scalar(q) or 0


def rooms_continued(
    session: Session, actor: Actor, continued: dict[uuid.UUID, uuid.UUID | None]
) -> None:
    """Помещения объединили или убрали (5.1.6 п. 3): предметы — к продолжающему; убранное —
    пересчитается по точке после сохранения."""
    for item in session.scalars(select(Item).where(Item.room_id.in_(list(continued)))):
        item.room_id = continued[item.room_id]  # type: ignore[index]


def plan_saved(session: Session, actor: Actor, floor_id: uuid.UUID) -> None:
    relocate(session, floor_id)


def floor_guard(session: Session, floor_id: uuid.UUID) -> None:
    count = session.scalar(select(func.count()).select_from(Item).where(Item.floor_id == floor_id))
    if count:
        raise Conflict(
            f"На этаже стоят предметы ({count}) — сначала уберите их в режиме «Расстановка».",
            code="not_empty",
        )
