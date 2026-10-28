"""Расстановка (5.3.2): предметы на плане этажа.

Расстановка сохраняется каждым действием (6.5.2): действие редактора — одна пачка изменений
(поставить, передвинуть, убрать), применяется целиком в одной транзакции и одной записью
журнала. Отмена в редакторе — такая же пачка с обратными изменениями; поэтому предмет можно
поставить заново с тем же ключом.
"""

import math
import uuid
from collections import Counter
from collections.abc import Callable
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
FIELDS = ("x", "y", "angle", "z", "parent_id", "label", "model_id", "unit_id", "params")


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
        "unit_id": item.unit_id,
        "params": item.params or {},
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


def _params(value: Any) -> dict[str, Any]:
    """Параметры для расчётов: «модуль.параметр» → число, текст или да/нет."""
    if value in (None, ""):
        return {}
    if not isinstance(value, dict) or len(value) > 30:
        raise AppError("Параметры расчётов: неверный вид.", field="params")
    out: dict[str, Any] = {}
    for k, v in value.items():
        if not isinstance(k, str) or len(k) > 40:
            raise AppError("Параметры расчётов: неверное название.", field="params")
        if isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, int | float):
            out[k] = _number(v, k, -1e6, 1e6)
        elif isinstance(v, str) and len(v) <= 100:
            out[k] = v
        else:
            raise AppError(f"Параметр «{k}»: неверное значение.", field="params")
    return out


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
        if "params" in values:
            item.params = _params(values["params"])
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
            params={},
            version=1,
        )
        self.link(item, values.get("unit_id"))
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
        if "unit_id" in changes:
            self.link(item, changes["unit_id"])
        # вынуть из вместилища — поставить рядом с ним, если точку не дали
        if "parent_id" in changes and changes["parent_id"] in (None, "") and item.parent_id:
            parent = self.items[item.parent_id]
            changes.setdefault("x", parent.x)
            changes.setdefault("y", parent.y)
        self.place(item, changes)
        if item not in self.created and item not in self.updated:
            self.updated.append(item)
        return item

    def link(self, item: Item, value: Any) -> None:
        """Связь с инвентарной единицей (5.5): одна единица — один предмет. Что за единица
        и где числится, проверяет модуль связи."""
        unit_id = _uuid(value, "unit_id")
        if unit_id is not None:
            here = any(i.unit_id == unit_id and i.id != item.id for i in self.items.values())
            gone = {i.id for i in self.deleted}
            other = self.session.scalar(
                select(Item.id).where(Item.unit_id == unit_id, Item.id != item.id)
            )
            if here or (other is not None and other not in gone):
                raise Conflict("Эта инвентарная единица уже стоит на плане.", code="linked")
        item.unit_id = unit_id

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
        return {"items": [], "deleted": [], "notes": []}
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
    # модули выше (связь с учётом) узнают, что стоит где теперь; вложенные — вместе со
    # своими вместилищами, их помещение могло смениться
    ids = {i.id for i in touched}
    moved_along = [i for i in batch.items.values() if i.parent_id in ids and i.id not in ids]
    notes: list[str] = []
    for hook in _changed_hooks:
        notes.extend(hook(session, actor, [*touched, *moved_along], batch.deleted))

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
    return {
        "items": [item_view(i) for i in touched],
        "deleted": [str(i) for i in deleted_ids],
        "notes": notes,
    }


def _room_titles(session: Session, actor: Actor, ids: set[uuid.UUID | None]) -> list[str]:
    out = []
    for rid in ids:
        if rid is None:
            continue
        out.append(building.room_title(building.get_room(session, actor, rid)))
    return out


# ---------------------------------------------------------------- для модулей выше

# (session, actor, поставленные и изменённые, убранные) → пояснения для человека
ChangedHook = Callable[[Session, Actor, list[Item], list[Item]], list[str]]
_changed_hooks: list[ChangedHook] = []


def on_items_changed(hook: ChangedHook) -> None:
    """Подписаться на действия расстановки: вызывается в той же транзакции; ошибка в
    подписчике отменяет всё действие."""
    if hook not in _changed_hooks:  # повторная подписка не удваивает (R-013)
        _changed_hooks.append(hook)


def items_of_units(session: Session, unit_ids: list[uuid.UUID]) -> dict[uuid.UUID, Item]:
    if not unit_ids:
        return {}
    rows = session.scalars(select(Item).where(Item.unit_id.in_(unit_ids)))
    return {i.unit_id: i for i in rows if i.unit_id}


def items_by_id(session: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, Item]:
    if not item_ids:
        return {}
    return {i.id: i for i in session.scalars(select(Item).where(Item.id.in_(item_ids)))}


def floor_items_raw(session: Session, floor_id: uuid.UUID) -> list[Item]:
    return list(session.scalars(select(Item).where(Item.floor_id == floor_id)))


def link_unit(session: Session, item: Item, unit_id: uuid.UUID | None) -> None:
    """Связать предмет с единицей (постановка на учёт с плана)."""
    item.unit_id = unit_id
    item.version += 1
    item.updated_at = datetime.now(UTC)


def remove_items(session: Session, actor: Actor, items: list[Item]) -> list[str]:
    """Убрать предметы с плана (их единицы ушли документом) — обычным действием
    расстановки, с записью в журнал. Ключи убранных."""
    out: list[str] = []
    by_floor: dict[uuid.UUID, list[Item]] = {}
    for item in items:
        by_floor.setdefault(item.floor_id, []).append(item)
    for floor_id, rows in by_floor.items():
        r = apply_changes(session, actor, floor_id, Changes(delete=[{"id": i.id} for i in rows]))
        out.extend(r["deleted"])
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


# ---------------------------------------------------------------- перенос здания


def transfer_export(session: Session, actor: Actor, building_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.modules.planning import transfer

    return transfer.export(session, actor, building_id)


def transfer_load(
    session: Session,
    actor: Actor,
    items: list[dict[str, Any]],
    floors: dict[str, uuid.UUID],
    types: dict[str, uuid.UUID | None],
    models: dict[str, uuid.UUID | None],
    units: dict[str, uuid.UUID],
) -> int:
    from app.modules.planning import transfer

    return transfer.load(session, actor, items, floors, types, models, units)
