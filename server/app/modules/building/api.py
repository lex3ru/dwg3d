"""Программный интерфейс модуля «Здание и план» для других модулей и его маршрутов.

Права: администратор видит все здания, «просмотр» — выданные (2.2); чужое здание для него
не существует (ответ «не найдено», а не «запрещено»). Меняет только администратор."""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from shapely.geometry import Polygon
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import search
from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound, stale
from app.modules.building import geometry
from app.modules.building.models import Building, Floor, Lift, Room
from app.modules.building.plan import EMPTY, Plan, RoomLabel
from app.modules.journal import api as journal

# ---------------------------------------------------------------- доступ к зданиям


def _visible(actor: Actor, building: Building) -> bool:
    return actor.is_admin or building.id in actor.building_ids


def _require_admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden()


def get_building(session: Session, actor: Actor, building_id: uuid.UUID) -> Building:
    building = session.get(Building, building_id)
    if building is None or not _visible(actor, building):
        raise NotFound("Здание не найдено.")
    return building


def get_floor(session: Session, actor: Actor, floor_id: uuid.UUID) -> Floor:
    floor = session.get(Floor, floor_id)
    if floor is None:
        raise NotFound("Этаж не найден.")
    get_building(session, actor, floor.building_id)
    return floor


class Directory:
    """Справочник зданий для модуля доступа (выдача «просмотра» на здание)."""

    def names(self, session: Session, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = list(ids)
        if not ids:
            return {}
        rows = session.execute(select(Building.id, Building.name).where(Building.id.in_(ids)))
        return {row.id: row.name for row in rows}


# ---------------------------------------------------------------- здания (5.1.1)

def _counts(session: Session, building_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    floors = dict(session.execute(select(Floor.building_id, func.count()).where(
        Floor.building_id.in_(building_ids)).group_by(Floor.building_id)).all())
    rooms = dict(session.execute(select(Room.building_id, func.count()).where(
        Room.building_id.in_(building_ids), Room.archived_at.is_(None))
        .group_by(Room.building_id)).all())
    return {b: (floors.get(b, 0), rooms.get(b, 0)) for b in building_ids}


def building_view(building: Building, counts: tuple[int, int] = (0, 0)) -> dict[str, Any]:
    return {"id": building.id, "name": building.name, "address": building.address,
            "archived": building.archived_at is not None, "archived_at": building.archived_at,
            "floors": counts[0], "rooms": counts[1], "version": building.version}


def list_buildings(session: Session, actor: Actor, archived: bool = False
                   ) -> list[dict[str, Any]]:
    query = select(Building).order_by(Building.name)
    if not archived:
        query = query.where(Building.archived_at.is_(None))
    if not actor.is_admin:
        query = query.where(Building.id.in_(actor.building_ids or [uuid.uuid4()]))
    buildings = list(session.scalars(query))
    counts = _counts(session, [b.id for b in buildings])
    return [building_view(b, counts[b.id]) for b in buildings]


def _check_name(name: str, what: str = "название") -> str:
    name = name.strip()
    if not name:
        raise AppError(f"Укажите {what}.", field="name", code="required")
    return name


def create_building(session: Session, actor: Actor, name: str, address: str = ""
                    ) -> Building:
    _require_admin(actor)
    building = Building(id=uuid.uuid4(), name=_check_name(name), address=address.strip(),
                        version=1)
    session.add(building)
    session.flush()
    journal.record(session, actor, "building.create", f"Создано здание «{building.name}»",
                   entity=f"building:{building.id}",
                   after={"name": building.name, "address": building.address})
    return building


def update_building(session: Session, actor: Actor, building_id: uuid.UUID, version: int,
                    name: str | None = None, address: str | None = None) -> Building:
    _require_admin(actor)
    building = get_building(session, actor, building_id)
    if building.version != version:
        raise stale("Здание")
    before = {"name": building.name, "address": building.address}
    if name is not None:
        building.name = _check_name(name)
    if address is not None:
        building.address = address.strip()
    was, became = journal.changes(before, {"name": building.name, "address": building.address})
    if became:
        building.version += 1
        journal.record(session, actor, "building.update",
                       f"Изменено здание «{building.name}»", entity=f"building:{building.id}",
                       before=was, after=became)
    return building


def set_archived(session: Session, actor: Actor, building_id: uuid.UUID, archived: bool
                 ) -> Building:
    _require_admin(actor)
    building = get_building(session, actor, building_id)
    if (building.archived_at is not None) == archived:
        return building
    building.archived_at = datetime.now(UTC) if archived else None
    building.version += 1
    what = "отправлено в архив" if archived else "возвращено из архива"
    journal.record(session, actor, "building.archive" if archived else "building.unarchive",
                   f"Здание «{building.name}» {what}", entity=f"building:{building.id}")
    return building


_on_building_deleted: list[Callable[[Session, uuid.UUID], None]] = []


def on_building_deleted(callback: Callable[[Session, uuid.UUID], None]) -> None:
    _on_building_deleted.append(callback)


def delete_building(session: Session, actor: Actor, building_id: uuid.UUID) -> None:
    _require_admin(actor)
    building = get_building(session, actor, building_id)
    if session.scalar(select(func.count()).select_from(Floor)
                      .where(Floor.building_id == building.id)):
        raise Conflict("Удалить можно только пустое здание — сначала удалите его этажи "
                       "или отправьте здание в архив.", code="not_empty")
    for callback in _on_building_deleted:
        callback(session, building.id)
    session.delete(building)
    journal.record(session, actor, "building.delete", f"Удалено здание «{building.name}»",
                   entity=f"building:{building.id}", before={"name": building.name})


# ---------------------------------------------------------------- этажи (5.1.2)

def floors(session: Session, building_id: uuid.UUID) -> list[Floor]:
    return list(session.scalars(select(Floor).where(Floor.building_id == building_id)
                                .order_by(Floor.position)))


def floor_view(session: Session, floor: Floor) -> dict[str, Any]:
    rooms = session.scalar(select(func.count()).select_from(Room).where(
        Room.floor_id == floor.id, Room.archived_at.is_(None))) or 0
    plan = floor.plan or {}
    return {"id": floor.id, "building_id": floor.building_id, "name": floor.name,
            "position": floor.position, "elevation": floor.elevation, "height": floor.height,
            "rooms": rooms, "walls": len(plan.get("walls", [])),
            "plan_version": floor.plan_version, "plan_saved_at": floor.plan_saved_at,
            "version": floor.version}


def add_floor(session: Session, actor: Actor, building_id: uuid.UUID, name: str,
              elevation: float | None = None, height: float = 3300,
              copy_bearing_from: uuid.UUID | None = None) -> Floor:
    _require_admin(actor)
    building = get_building(session, actor, building_id)
    existing = floors(session, building.id)
    if height <= 0 or height > 30000:
        raise AppError("Высота этажа — от 1 до 30 000 мм.", field="height")
    if elevation is None:
        top = existing[-1] if existing else None
        elevation = top.elevation + top.height if top else 0
    plan: dict[str, Any] = dict(EMPTY)
    if copy_bearing_from is not None:
        source = get_floor(session, actor, copy_bearing_from)
        plan = _bearing_only(Plan.model_validate(source.plan)).model_dump()
    floor = Floor(id=uuid.uuid4(), building_id=building.id, name=_check_name(name),
                  position=(existing[-1].position + 1) if existing else 0,
                  elevation=elevation, height=height, plan=plan, plan_version=1, version=1)
    # этажи — по отметке пола
    session.add(floor)
    session.flush()
    _renumber(session, building.id)
    journal.record(session, actor, "floor.create",
                   f"Добавлен этаж «{floor.name}» в здании «{building.name}»",
                   entity=f"floor:{floor.id}", refs=[f"building:{building.id}"],
                   after={"name": floor.name, "elevation": elevation, "height": height})
    return floor


def _bearing_only(plan: Plan) -> Plan:
    walls = [w for w in plan.walls if w.kind == "bearing"]
    used = {n for w in walls for n in (w.a, w.b)}
    return Plan(nodes={k: v for k, v in plan.nodes.items() if k in used}, walls=walls,
                columns=plan.columns)


def _renumber(session: Session, building_id: uuid.UUID) -> None:
    ordered = sorted(floors(session, building_id), key=lambda f: (f.elevation, f.position))
    for i, floor in enumerate(ordered):
        floor.position = i


def update_floor(session: Session, actor: Actor, floor_id: uuid.UUID, version: int,
                 name: str | None = None, elevation: float | None = None,
                 height: float | None = None) -> Floor:
    _require_admin(actor)
    floor = get_floor(session, actor, floor_id)
    if floor.version != version:
        raise stale("Этаж")
    before = {"name": floor.name, "elevation": floor.elevation, "height": floor.height}
    if name is not None:
        floor.name = _check_name(name)
    if elevation is not None:
        floor.elevation = elevation
    if height is not None:
        if height <= 0 or height > 30000:
            raise AppError("Высота этажа — от 1 до 30 000 мм.", field="height")
        floor.height = height
    after = {"name": floor.name, "elevation": floor.elevation, "height": floor.height}
    was, became = journal.changes(before, after)
    if became:
        floor.version += 1
        session.flush()
        _renumber(session, floor.building_id)
        journal.record(session, actor, "floor.update", f"Изменён этаж «{floor.name}»",
                       entity=f"floor:{floor.id}", refs=[f"building:{floor.building_id}"],
                       before=was, after=became)
    return floor


# модули выше проверяют, можно ли удалить этаж (на нём предметы): бросают Conflict
_floor_guards: list[Callable[[Session, uuid.UUID], None]] = []


def guard_floor_delete(check: Callable[[Session, uuid.UUID], None]) -> None:
    _floor_guards.append(check)


def delete_floor(session: Session, actor: Actor, floor_id: uuid.UUID) -> None:
    _require_admin(actor)
    floor = get_floor(session, actor, floor_id)
    plan = floor.plan or {}
    if plan.get("walls") or session.scalar(select(func.count()).select_from(Room).where(
            Room.floor_id == floor.id)):
        raise Conflict("Удалить можно только пустой этаж — на этом есть план или помещения.",
                       code="not_empty")
    for check in _floor_guards:
        check(session, floor.id)
    for lift in session.scalars(select(Lift).where(Lift.building_id == floor.building_id)):
        if floor.id in lift.floor_ids:
            lift.floor_ids = [f for f in lift.floor_ids if f != floor.id]
            lift.stop_ids = [f for f in lift.stop_ids if f != floor.id]
    session.delete(floor)
    session.flush()
    _renumber(session, floor.building_id)
    journal.record(session, actor, "floor.delete", f"Удалён этаж «{floor.name}»",
                   entity=f"floor:{floor.id}", refs=[f"building:{floor.building_id}"],
                   before={"name": floor.name})


# ---------------------------------------------------------------- помещения

def room_view(room: Room) -> dict[str, Any]:
    return {"id": room.id, "floor_id": room.floor_id, "number": room.number,
            "name": room.name, "purpose_id": room.purpose_id, "area": room.area,
            "outline": room.outline, "x": room.x, "y": room.y,
            "archived": room.archived_at is not None, "continued_by": room.continued_by}


def room_title(room: Room) -> str:
    return " ".join(p for p in (room.number, room.name) if p) or "помещение без номера"


def live_rooms(session: Session, floor_id: uuid.UUID) -> list[Room]:
    return list(session.scalars(select(Room).where(Room.floor_id == floor_id,
                                                   Room.archived_at.is_(None))
                                .order_by(Room.number, Room.name)))


def room_ids_of(session: Session, building_id: uuid.UUID) -> list[uuid.UUID]:
    """Все помещения здания, и убранные тоже — по ним документы прошлых лет."""
    return list(session.scalars(select(Room.id).where(Room.building_id == building_id)))


def rooms_with_floor(session: Session, actor: Actor, room_ids: Iterable[uuid.UUID]
                     ) -> list[tuple[Room, str]]:
    """Помещения пачкой с названием их этажа — для подписей мест (8.1: тысячи помещений
    одним запросом); помещения недоступных зданий пропускаются."""
    ids = list(set(room_ids))
    out: list[tuple[Room, str]] = []
    for i in range(0, len(ids), 5000):
        rows = session.execute(select(Room, Floor.name).join(Floor, Floor.id == Room.floor_id)
                               .where(Room.id.in_(ids[i:i + 5000])))
        out += [(room, name) for room, name in rows
                if actor.is_admin or actor.can_see_building(room.building_id)]
    return out


def get_room(session: Session, actor: Actor, room_id: uuid.UUID) -> Room:
    room = session.get(Room, room_id)
    if room is None:
        raise NotFound("Помещение не найдено.")
    get_building(session, actor, room.building_id)
    return room


# что делать модулям выше, когда помещения объединяются или убираются (5.1.6 п. 3):
# {старое помещение: продолжающее или None}
_on_rooms_continued: list[Callable[[Session, Actor, dict[uuid.UUID, uuid.UUID | None]], None]] \
    = []


def on_rooms_continued(callback: Callable[[Session, Actor, dict[uuid.UUID, uuid.UUID | None]],
                                          None]) -> None:
    _on_rooms_continued.append(callback)


# после сохранения плана: помещения этажа могли поменять очертания — модули выше
# пересчитывают, что в каком помещении стоит
_on_plan_saved: list[Callable[[Session, Actor, uuid.UUID], None]] = []


def on_plan_saved(callback: Callable[[Session, Actor, uuid.UUID], None]) -> None:
    _on_plan_saved.append(callback)


# ---------------------------------------------------------------- план (5.1.4–5.1.6)

@dataclass
class Change:
    """Что сохранение плана сделает с помещениями."""

    shapes: list[geometry.RoomShape]
    # для каждой фигуры: продолжающее помещение (существующее), или None — новое
    keeps: list[uuid.UUID | None] = field(default_factory=list)
    merges: list[tuple[int, list[uuid.UUID]]] = field(default_factory=list)
    unresolved: list[tuple[int, list[uuid.UUID]]] = field(default_factory=list)
    splits: list[tuple[int, uuid.UUID]] = field(default_factory=list)
    removed: list[uuid.UUID] = field(default_factory=list)

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.merges or self.splits or self.removed)


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _changes(session: Session, floor: Floor, plan: Plan, analysis: geometry.Analysis,
             merges: list[dict[str, Any]]) -> Change:
    live = {r.id: r for r in live_rooms(session, floor.id)}
    change = Change(shapes=analysis.rooms)
    claimed: set[uuid.UUID] = set()
    for i, shape in enumerate(analysis.rooms):
        existing = [rid for rid in (_as_uuid(lbl) for lbl in shape.labels)
                    if rid is not None and rid in live]
        keep: uuid.UUID | None = existing[0] if existing else None
        if len(existing) > 1:
            chosen = next((m.get("keep") for m in merges
                           if set(map(str, m.get("rooms", []))) == set(map(str, existing))),
                          None)
            chosen_id = _as_uuid(str(chosen)) if chosen else None
            if chosen_id in existing:
                keep = chosen_id
                change.merges.append((i, existing))
            else:
                change.unresolved.append((i, existing))
                change.merges.append((i, existing))
        change.keeps.append(keep)
        claimed.update(existing)
    change.removed = [rid for rid in live if rid not in claimed]
    # деление: новая фигура лежит в основном внутри прежнего контура помещения
    for i, shape in enumerate(analysis.rooms):
        if change.keeps[i] is not None:
            continue
        for rid, room in live.items():
            if rid not in claimed or len(room.outline) < 3:
                continue
            old = Polygon(room.outline)
            if old.is_valid and shape.polygon.intersection(old).area > 0.5 * shape.polygon.area:
                change.splits.append((i, rid))
                break
    return change


def _preview(session: Session, change: Change, plan: Plan) -> dict[str, Any]:
    live = {r.id: r for r in session.scalars(select(Room).where(
        Room.id.in_([*filter(None, change.keeps), *change.removed,
                     *[r for _, ids in change.merges for r in ids]])))}
    labels = {lbl.id: lbl for lbl in plan.rooms}

    def brief(rid: uuid.UUID) -> dict[str, Any]:
        room = live[rid]
        return {"id": rid, "number": room.number, "name": room.name, "title": room_title(room)}

    rooms = []
    for i, shape in enumerate(change.shapes):
        label = next((labels[lbl] for lbl in shape.labels if lbl in labels), None)
        keep = change.keeps[i]
        status = "kept" if keep else "new"
        if any(j == i for j, _ in change.merges):
            status = "merged"
        x, y = (label.x, label.y) if label else shape.anchor()
        rooms.append({"index": i, "id": keep, "label": label.id if label else None,
                      "labels": list(shape.labels),
                      "number": label.number if label else "",
                      "name": label.name if label else "", "area": shape.area_m2,
                      "outline": shape.outline(), "x": x, "y": y, "status": status})
    return {
        "rooms": rooms,
        "merges": [{"index": i, "rooms": [brief(r) for r in ids],
                    "keep": change.keeps[i] if (i, ids) not in change.unresolved else None}
                   for i, ids in change.merges],
        "splits": [{"index": i, "from": brief(rid)} for i, rid in change.splits],
        "removed": [brief(r) for r in change.removed],
        "needs_confirmation": change.needs_confirmation,
    }


def _lifts_on(session: Session, floor: Floor) -> list[Lift]:
    return [lift for lift in session.scalars(select(Lift).where(
        Lift.building_id == floor.building_id)) if floor.id in lift.floor_ids]


def lift_view(lift: Lift) -> dict[str, Any]:
    return {"id": lift.id, "name": lift.name, "x": lift.x, "y": lift.y, "w": lift.w,
            "d": lift.d, "angle": lift.angle, "door_side": lift.door_side,
            "floor_ids": lift.floor_ids, "stop_ids": lift.stop_ids}


def building_files(session: Session, actor: Actor, building_id: uuid.UUID
                   ) -> list[tuple[str, uuid.UUID, str]]:
    """Файлы здания для полной выгрузки (7.4): чертежи и подложки — (папка, файл, подпись)."""
    from app.modules.building.models import Drawing

    get_building(session, actor, building_id)
    out: list[tuple[str, uuid.UUID, str]] = []
    for d in session.scalars(select(Drawing).where(Drawing.building_id == building_id)):
        out.append(("чертежи", d.file_id, d.name))
    for f in floors(session, building_id):
        underlay = (f.plan or {}).get("underlay") or {}
        if underlay.get("file_id"):
            out.append(("подложки", uuid.UUID(underlay["file_id"]), f.name))
    return out


def is_underlay_file(session: Session, actor: Actor, file_id: uuid.UUID) -> bool:
    floors = select(Floor).where(Floor.building_id.in_(list(actor.building_ids)))
    for floor in session.scalars(floors):
        underlay = (floor.plan or {}).get("underlay") or {}
        if underlay.get("file_id") == str(file_id):
            return True
    return False


def floor_obstacles(session: Session, actor: Actor, floor_id: uuid.UUID) -> list[Any]:
    """Стены (без дверей и проходов) и колонны этажа — что закрывает обзор (расчёты)."""
    floor = get_floor(session, actor, floor_id)
    return geometry.obstacles(Plan.model_validate(floor.plan or {}))


def plan_view(session: Session, actor: Actor, floor: Floor) -> dict[str, Any]:
    plan = Plan.model_validate(floor.plan or {})
    analysis = geometry.analyze(plan)
    building = session.get(Building, floor.building_id)
    return {
        "floor": floor_view(session, floor),
        "building": building_view(building) if building else None,
        "floors": [floor_view(session, f) for f in floors(session, floor.building_id)],
        "plan": plan.model_dump(),
        "plan_version": floor.plan_version,
        "rooms": [room_view(r) for r in live_rooms(session, floor.id)],
        "slabs": [[[round(x, 1), round(y, 1)] for x, y in s.exterior.coords[:-1]]
                  for s in analysis.slabs],
        "issues": [i.view() for i in analysis.issues] if actor.is_admin else [],
        "lifts": [lift_view(lift) for lift in session.scalars(select(Lift).where(
            Lift.building_id == floor.building_id))],
    }


def check_plan(session: Session, actor: Actor, floor_id: uuid.UUID, plan: Plan,
               merges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Что получится, если сохранить: помещения, замечания проверки, изменения помещений."""
    _require_admin(actor)
    floor = get_floor(session, actor, floor_id)
    analysis = geometry.analyze(plan)
    change = _changes(session, floor, plan, analysis, merges or [])
    return {"issues": [i.view() for i in analysis.issues], **_preview(session, change, plan),
            "slabs": [[[round(x, 1), round(y, 1)] for x, y in s.exterior.coords[:-1]]
                      for s in analysis.slabs]}


def fix_plan(actor: Actor, plan: Plan) -> dict[str, Any]:
    _require_admin(actor)
    fixed, done = geometry.fix(plan)
    left = geometry.analyze(fixed).issues
    return {"plan": fixed.model_dump(), "fixed": done, "issues": [i.view() for i in left]}


def save_plan(session: Session, actor: Actor, floor_id: uuid.UUID, plan: Plan,
              plan_version: int, merges: list[dict[str, Any]] | None = None,
              confirm: bool = False, auto_merge: bool = False) -> dict[str, Any]:
    """Сохранить план этажа с помещениями (5.1.6) — целиком или никак. auto_merge —
    при объединении остаётся первое помещение (перевод чертежа заново)."""
    _require_admin(actor)
    floor = session.get(Floor, floor_id, with_for_update=True)
    if floor is None:
        raise NotFound("Этаж не найден.")
    get_building(session, actor, floor.building_id)
    if floor.plan_version != plan_version:
        raise Conflict("План этого этажа уже сохранил другой пользователь. Ваши правки "
                       "остались в редакторе — обновите план, чтобы увидеть чужие.",
                       code="stale")
    analysis = geometry.analyze(plan)
    change = _changes(session, floor, plan, analysis, merges or [])
    if auto_merge and change.unresolved:
        merges = [{"rooms": [str(r) for r in ids], "keep": str(ids[0])}
                  for _, ids in change.unresolved]
        change = _changes(session, floor, plan, analysis, merges)
    if change.unresolved or (change.needs_confirmation and not confirm):
        error = Conflict("Сохранение изменит помещения — подтвердите.",
                         code="needs_confirmation")
        error.details = _preview(session, change, plan)
        raise error

    now = datetime.now(UTC)
    labels = {lbl.id: lbl for lbl in plan.rooms}
    live = {r.id: r for r in live_rooms(session, floor.id)}
    new_labels: list[RoomLabel] = []
    created: list[Room] = []
    kept: list[Room] = []
    continued: dict[uuid.UUID, uuid.UUID | None] = {}
    merged_titles: list[str] = []
    label_ids: dict[str, str] = {}

    for i, shape in enumerate(analysis.rooms):
        keep = change.keeps[i]
        own = [labels[lbl] for lbl in shape.labels if lbl in labels]
        label = next((lbl for lbl in own if _as_uuid(lbl.id) == keep), None) if keep else None
        label = label or (own[0] if own else None)
        if keep is not None:
            room = live[keep]
            others = [rid for j, ids in change.merges if j == i for rid in ids if rid != keep]
            if others:
                together = sorted([keep, *others], key=lambda r: (live[r].number, live[r].name))
                merged_titles.append(" + ".join(room_title(live[r]) for r in together)
                                     + f" → {room_title(room)}")
            for rid in others:
                live[rid].archived_at = now
                live[rid].continued_by = keep
                continued[rid] = keep
        else:
            room = Room(id=uuid.uuid4(), building_id=floor.building_id, floor_id=floor.id)
            session.add(room)
            created.append(room)
        x, y = (label.x, label.y) if label else shape.anchor()
        room.number = label.number if label else ""
        room.name = label.name if label else ""
        room.purpose_id = label.purpose_id if label else None
        room.area, room.outline, room.x, room.y = shape.area_m2, shape.outline(), x, y
        new_labels.append(RoomLabel(id=str(room.id), x=x, y=y, number=room.number,
                                    name=room.name, purpose_id=room.purpose_id))
        for lbl in own:
            label_ids[lbl.id] = str(room.id)
        if keep is not None:
            kept.append(room)
    for rid in change.removed:
        live[rid].archived_at = now
        continued[rid] = None

    saved = plan.model_copy(update={"rooms": new_labels})
    floor.plan = saved.model_dump()
    floor.plan_version += 1
    floor.plan_saved_at = now
    session.flush()
    for callback in _on_rooms_continued:
        if continued:
            callback(session, actor, continued)
    for saved_callback in _on_plan_saved:
        saved_callback(session, actor, floor.id)

    parts = [f"стен {len(plan.walls)}, проёмов {len(plan.openings)}, "
             f"помещений {len(analysis.rooms)}"]
    if created:
        parts.append("новые: " + ", ".join(room_title(r) for r in created))
    if merged_titles:
        parts.append("объединены: " + "; ".join(merged_titles))
    removed = [room_title(live[r]) for r in change.removed]
    if removed:
        parts.append("убраны: " + ", ".join(removed))
    refs = [f"building:{floor.building_id}",
            *[f"room:{r.id}" for r in [*created, *kept]],
            *[f"room:{r}" for r in continued]]
    journal.record(session, actor, "floor.plan_save",
                   f"Сохранён план «{floor.name}»: " + "; ".join(parts),
                   entity=f"floor:{floor.id}", refs=refs)
    view = plan_view(session, actor, floor)
    # подписи, которые получили ключ помещения (новые) или ушли с объединением
    view["label_ids"] = label_ids
    return view


# ---------------------------------------------------------------- лифты (5.1.4 п. 3)

def _lift_fields(session: Session, building_id: uuid.UUID, values: dict[str, Any]
                 ) -> dict[str, Any]:
    ids = {f.id for f in floors(session, building_id)}
    out = dict(values)
    for key in ("floor_ids", "stop_ids"):
        if key in out and out[key] is not None:
            out[key] = [uuid.UUID(str(f)) for f in out[key]]
            if not set(out[key]) <= ids:
                raise AppError("Этаж лифта не из этого здания.", field=key)
    if "floor_ids" in out and out["floor_ids"] is not None and len(out["floor_ids"]) < 1:
        raise AppError("Шахта лифта должна проходить хотя бы через один этаж.",
                       field="floor_ids")
    for key in ("w", "d"):
        if key in out and out[key] is not None and not 300 <= out[key] <= 10000:
            raise AppError("Размер шахты — от 300 до 10 000 мм.", field=key)
    return {k: v for k, v in out.items() if v is not None}


def create_lift(session: Session, actor: Actor, building_id: uuid.UUID, values: dict[str, Any]
                ) -> Lift:
    _require_admin(actor)
    building = get_building(session, actor, building_id)
    fields = _lift_fields(session, building.id, values)
    fields.setdefault("stop_ids", fields.get("floor_ids", []))
    lift = Lift(id=uuid.uuid4(), building_id=building.id, **fields)
    session.add(lift)
    session.flush()
    journal.record(session, actor, "lift.create",
                   " ".join(filter(None, ["Поставлен лифт", lift.name,
                                          f"в здании «{building.name}»"])),
                   entity=f"lift:{lift.id}", refs=[f"building:{building.id}",
                                                   *[f"floor:{f}" for f in lift.floor_ids]])
    return lift


def update_lift(session: Session, actor: Actor, lift_id: uuid.UUID, values: dict[str, Any]
                ) -> Lift:
    _require_admin(actor)
    lift = session.get(Lift, lift_id)
    if lift is None:
        raise NotFound("Лифт не найден.")
    get_building(session, actor, lift.building_id)
    for key, value in _lift_fields(session, lift.building_id, values).items():
        setattr(lift, key, value)
    lift.stop_ids = [f for f in lift.stop_ids if f in lift.floor_ids]
    journal.record(session, actor, "lift.update", f"Изменён лифт {lift.name}".strip(),
                   entity=f"lift:{lift.id}", refs=[f"building:{lift.building_id}",
                                                   *[f"floor:{f}" for f in lift.floor_ids]])
    return lift


def delete_lift(session: Session, actor: Actor, lift_id: uuid.UUID) -> None:
    _require_admin(actor)
    lift = session.get(Lift, lift_id)
    if lift is None:
        raise NotFound("Лифт не найден.")
    get_building(session, actor, lift.building_id)
    session.delete(lift)
    journal.record(session, actor, "lift.delete", f"Убран лифт {lift.name}".strip(),
                   entity=f"lift:{lift.id}", refs=[f"building:{lift.building_id}"])


# ---------------------------------------------------------------- поиск (6.3)

def _search(session: Session, actor: Actor, query: str) -> list[search.Hit]:
    like = f"%{query}%"
    visible = None if actor.is_admin else list(actor.building_ids)
    q = (select(Room, Floor.name, Building.name).join(Floor, Room.floor_id == Floor.id)
         .join(Building, Room.building_id == Building.id)
         .where(Room.archived_at.is_(None), Building.archived_at.is_(None),
                (Room.number.ilike(like)) | (Room.name.ilike(like)))
         .order_by(Room.number).limit(15))
    if visible is not None:
        q = q.where(Room.building_id.in_(visible or [uuid.uuid4()]))
    hits = [search.Hit("Помещения", room_title(room), f"{building} · {floor}",
                       f"/plan/{room.building_id}/{room.floor_id}?room={room.id}")
            for room, floor, building in session.execute(q)]
    bq = select(Building).where(Building.name.ilike(like), Building.archived_at.is_(None))
    if visible is not None:
        bq = bq.where(Building.id.in_(visible or [uuid.uuid4()]))
    hits += [search.Hit("Здания", b.name, b.address, f"/plan/{b.id}")
             for b in session.scalars(bq.limit(5))]
    return hits


search.register(_search)


# ---------------------------------------------------------------- печать и выгрузка (5.1.8)

def floor_svg(session: Session, actor: Actor, floor_id: uuid.UUID, width_mm: float,
              height_mm: float, overlays: list[dict[str, Any]]) -> tuple[str, int]:
    """План этажа рисунком SVG на листе заданного размера, с фигурами модулей выше поверх
    (листы проекта, 5.3.6 п. 6). Возвращает рисунок и масштаб."""
    from app.modules.building import export

    floor = get_floor(session, actor, floor_id)
    plan = Plan.model_validate(floor.plan or {})
    rooms = [room_view(r) for r in live_rooms(session, floor.id)]
    lifts = [lift_view(lift) for lift in session.scalars(
        select(Lift).where(Lift.building_id == floor.building_id))]
    return export.fit_svg(export.drawing(plan, rooms, lifts, str(floor.id)), width_mm,
                          height_mm, overlays)


def export_floor(session: Session, actor: Actor, floor_id: uuid.UUID, fmt: str,
                 paper: str = "A4", orientation: str = "landscape",
                 scale: int | None = None, overlays: list[dict[str, Any]] | None = None
                 ) -> tuple[bytes, str]:
    from app.modules.building import export
    from app.modules.system import api as system

    floor = get_floor(session, actor, floor_id)
    building = session.get(Building, floor.building_id)
    assert building is not None
    plan = Plan.model_validate(floor.plan or {})
    rooms = [room_view(r) for r in live_rooms(session, floor.id)]
    lifts = [lift_view(lift) for lift in session.scalars(
        select(Lift).where(Lift.building_id == floor.building_id))]
    drawing = export.drawing(plan, rooms, lifts, str(floor.id))
    name = f"{building.name} — {floor.name}"
    if fmt == "dxf":
        return export.dxf(drawing, overlays), f"{name}.dxf"
    if paper not in export.PAPERS or orientation not in ("landscape", "portrait"):
        raise AppError("Лист — А4 или А3, книжный или альбомный.")
    if scale is not None and scale not in export.SCALES:
        raise AppError("Такого масштаба нет.", field="scale")
    data = export.pdf(drawing, paper=paper, orientation=orientation, scale=scale,
                      title=building.name, organization=system.get(session, "organization_name"),
                      floor=floor.name, overlays=overlays)
    return data, f"{name}.pdf"
