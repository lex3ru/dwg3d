"""Проекты (5.3.6, С9): предлагаемые изменения расстановки здания — добавить, переместить,
изменить, убрать. Пока проект не применён, расстановка не меняется; проектов может быть
несколько для сравнения. Видит и ведёт только администратор.

Проект хранится как изменения поверх расстановки: у тронутого предмета расстановки
запомнено, каким он был (base). Если расстановку с тех пор меняли там, где проект что-то
меняет, проект «устарел» — и видно, какие изменения столкнулись. Применение переносит
изменения в расстановку одним действием: новые предметы — без связи, или с выданной со
склада единицей (перемещение оформляет связь планировки и учёта, 5.5), или «к закупке».
"""

import io
import math
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from html import escape
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound, stale
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.inventory import api as inventory
from app.modules.journal import api as journal
from app.modules.planning import api as planning
from app.modules.projects.models import Change, Project
from app.modules.system import api as system

POSITION = ("x", "y", "angle", "z", "parent_id")
EDIT = ("x", "y", "angle", "z", "parent_id", "label", "model_id", "params")
STATUS = {
    "draft": "черновик",
    "outdated": "устарел",
    "applied": "применён",
    "archived": "в архиве",
}


def _admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden()


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in d.items()}


def _uuid(value: Any, what: str = "id") -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        raise AppError(f"{what}: неверный ключ.", field=what) from None


def _number(value: Any, what: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise AppError(f"{what}: нужно число.", field=what) from None
    if not math.isfinite(v) or abs(v) > 1e8:
        raise AppError(f"{what}: вне допустимых пределов.", field=what)
    return v


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Поля предмета из редактора — в простом виде для хранения."""
    out: dict[str, Any] = {}
    for k in EDIT:
        if k not in values:
            continue
        v = values[k]
        if k in ("x", "y", "angle", "z"):
            out[k] = None if v is None and k in ("x", "y") else _number(v, k)
            if k == "angle" and out[k] is not None:
                out[k] %= 360
        elif k in ("parent_id", "model_id"):
            u = _uuid(v, k)
            out[k] = str(u) if u else None
        elif k == "label":
            out[k] = str(v or "").strip()[:100]
        elif k == "params":
            out[k] = (
                {
                    str(pk)[:40]: pv
                    for pk, pv in (v or {}).items()
                    if pv is None or isinstance(pv, bool | int | float | str)
                }
                if isinstance(v, dict)
                else {}
            )
    return out


def _base(item: Any) -> dict[str, Any]:
    view = _jsonable(planning.item_view(item))
    return {k: view.get(k) for k in EDIT}


# ---------------------------------------------------------------- проект


def get_project(session: Session, actor: Actor, project_id: uuid.UUID) -> Project:
    _admin(actor)
    p = session.get(Project, project_id)
    if p is None:
        raise NotFound("Проект не найден.")
    building.get_building(session, actor, p.building_id)
    return p


def _rows(session: Session, p: Project, floor_id: uuid.UUID | None = None) -> list[Change]:
    q = select(Change).where(Change.project_id == p.id)
    if floor_id is not None:
        q = q.where(Change.floor_id == floor_id)
    return list(session.scalars(q.order_by(Change.updated_at)))


def _status(p: Project, rows: list[Change], conflicts: int) -> str:
    if p.archived_at:
        return "archived"
    if p.applied_at and not rows:
        return "applied"
    return "outdated" if conflicts else "draft"


def project_view(session: Session, actor: Actor, p: Project) -> dict[str, Any]:
    rows = _rows(session, p)
    floors = {r.floor_id for r in rows}
    conflicts: list[dict[str, Any]] = []
    rooms: set[str] = set()
    for floor_id in floors:
        state = floor_state(session, actor, p, floor_id)
        conflicts += state["conflicts"]
        rooms |= set(state["rooms"])
    status = _status(p, rows, len(conflicts))
    return {
        "id": p.id,
        "building_id": p.building_id,
        "name": p.name,
        "status": status,
        "status_title": STATUS[status],
        "changes": len(rows),
        "added": sum(1 for r in rows if r.kind == "add"),
        "moved": sum(1 for r in rows if r.kind == "update"),
        "removed": sum(1 for r in rows if r.kind == "remove"),
        "rooms": sorted(rooms),
        "floor_ids": [str(f) for f in floors],
        "conflicts": conflicts,
        "total": float(specification(session, actor, p)["total"]),
        "created_by": p.created_by,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
        "applied_at": p.applied_at,
        "archived": p.archived_at is not None,
        "version": p.version,
    }


def projects(
    session: Session, actor: Actor, building_id: uuid.UUID | None, archived: bool = False
) -> list[Project]:
    _admin(actor)
    q = select(Project).order_by(Project.updated_at.desc())
    if building_id is not None:
        building.get_building(session, actor, building_id)
        q = q.where(Project.building_id == building_id)
    if not archived:
        q = q.where(Project.archived_at.is_(None))
    return list(session.scalars(q))


def _name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise AppError("Назовите проект.", field="name")
    if len(name) > 200:
        raise AppError("Название — до 200 знаков.", field="name")
    return name


def create_project(
    session: Session, actor: Actor, building_id: uuid.UUID, name: Any, copy_of: uuid.UUID | None
) -> Project:
    """Новый проект — из текущей расстановки (пустой) или копией другого (5.3.6 п. 1)."""
    _admin(actor)
    b = building.get_building(session, actor, building_id)
    p = Project(
        id=uuid.uuid4(), building_id=b.id, name=_name(name), created_by=actor.full_name, version=1
    )
    session.add(p)
    session.flush()
    source = None
    if copy_of is not None:
        source = get_project(session, actor, copy_of)
        if source.building_id != b.id:
            raise AppError("Копировать можно проект того же здания.")
        for r in _rows(session, source):
            session.add(
                Change(
                    project_id=p.id,
                    floor_id=r.floor_id,
                    item_id=r.item_id,
                    kind=r.kind,
                    fields=dict(r.fields),
                    base=dict(r.base),
                )
            )
    journal.record(
        session,
        actor,
        "project.create",
        f"Создан проект «{p.name}»" + (f" — копия «{source.name}»" if source else ""),
        entity=f"project:{p.id}",
        refs=[f"building:{b.id}"],
    )
    session.flush()
    return p


def update_project(
    session: Session, actor: Actor, project_id: uuid.UUID, version: int, values: dict[str, Any]
) -> Project:
    p = get_project(session, actor, project_id)
    if p.version != version:
        raise stale("Проект")
    parts = []
    if "name" in values:
        name = _name(values["name"])
        if name != p.name:
            parts.append(f"переименован: «{p.name}» → «{name}»")
            p.name = name
    if "archived" in values:
        archived = bool(values["archived"])
        if archived != (p.archived_at is not None):
            p.archived_at = datetime.now(UTC) if archived else None
            parts.append("отправлен в архив" if archived else "возвращён из архива")
    if parts:
        p.version += 1
        p.updated_at = datetime.now(UTC)
        journal.record(
            session,
            actor,
            "project.update",
            f"Проект «{p.name}»: " + "; ".join(parts),
            entity=f"project:{p.id}",
            refs=[f"building:{p.building_id}"],
        )
    return p


def delete_project(session: Session, actor: Actor, project_id: uuid.UUID) -> None:
    p = get_project(session, actor, project_id)
    journal.record(
        session,
        actor,
        "project.delete",
        f"Удалён проект «{p.name}»",
        entity=f"project:{p.id}",
        refs=[f"building:{p.building_id}"],
    )
    session.delete(p)


# ---------------------------------------------------------------- состояние этажа в проекте


def floor_state(session: Session, actor: Actor, p: Project, floor_id: uuid.UUID) -> dict[str, Any]:
    """Расстановка этажа, как она будет по проекту: предметы с отметкой «добавлен»,
    «перемещён», «изменён»; убранные — отдельно; столкновения с расстановкой."""
    layout = {
        str(i.id): _jsonable(planning.item_view(i))
        for i in planning.floor_items_raw(session, floor_id)
    }
    items = dict(layout)
    states: dict[str, str] = {}
    removed: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    rows = _rows(session, p, floor_id)
    types = catalog.types_by_id(
        session,
        [
            uuid.UUID(r.fields["type_id"])
            for r in rows
            if r.kind == "add" and r.fields.get("type_id")
        ]
        + [uuid.UUID(v["type_id"]) for v in layout.values()],
    )

    def name(type_id: Any) -> str:
        t = types.get(uuid.UUID(str(type_id))) if type_id else None
        return t.name if t else "предмет"

    for r in rows:
        iid = str(r.item_id)
        if r.kind == "add":
            items[iid] = {
                **r.fields,
                "id": iid,
                "floor_id": str(floor_id),
                "unit_id": None,
                "version": 1,
            }
            states[iid] = "added"
            continue
        cur = layout.get(iid)
        if cur is None:
            conflicts.append(
                {
                    "item_id": iid,
                    "floor_id": str(floor_id),
                    "kind": r.kind,
                    "text": f"«{name(r.base.get('type_id'))}» убрали из расстановки после того, "
                    "как проект его изменил",
                }
            )
            continue
        if any(cur.get(k) != r.base.get(k) for k in EDIT if k in r.base):
            conflicts.append(
                {
                    "item_id": iid,
                    "floor_id": str(floor_id),
                    "kind": r.kind,
                    "text": f"«{name(cur['type_id'])}» в расстановке с тех пор передвинули или "
                    "изменили",
                    "x": cur.get("x"),
                    "y": cur.get("y"),
                }
            )
        if r.kind == "remove":
            removed.append({**cur, "state": "removed"})
            items.pop(iid, None)
            states[iid] = "removed"
        else:
            items[iid] = {**cur, **r.fields}
            moved = any(k in r.fields and r.fields[k] != cur.get(k) for k in POSITION)
            states[iid] = "moved" if moved else "changed"
    rooms = planning.Rooms(session, floor_id)
    for iid, it in items.items():
        if states.get(iid) in ("added", "moved") and not it.get("parent_id"):
            rid = rooms.at(it.get("x"), it.get("y"))
            it["room_id"] = str(rid) if rid else None
    for it in items.values():
        parent = items.get(it.get("parent_id") or "")
        if parent:
            it["room_id"] = parent.get("room_id")
    titles = {str(r.id): building.room_title(r) for r in building.live_rooms(session, floor_id)}
    touched = {items[i].get("room_id") for i in states if i in items} | {
        x.get("room_id") for x in removed
    }
    return {
        "items": [{**it, "state": states.get(iid)} for iid, it in items.items()],
        "removed": removed,
        "conflicts": conflicts,
        "rooms": [titles[r] for r in touched if r in titles],
    }


def change_floor(
    session: Session,
    actor: Actor,
    project_id: uuid.UUID,
    floor_id: uuid.UUID,
    create: list[dict[str, Any]],
    update: list[dict[str, Any]],
    delete: list[dict[str, Any]],
) -> dict[str, Any]:
    """Действие редактора в проекте (5.3.6 п. 2): та же пачка «поставить, изменить, убрать»,
    что и в расстановке, — но меняет проект, а не расстановку."""
    p = get_project(session, actor, project_id)
    if p.archived_at:
        raise Conflict("Проект в архиве — его не правят. Верните его из архива.")
    floor = building.get_floor(session, actor, floor_id)
    if floor.building_id != p.building_id:
        raise AppError("Этаж — другого здания.")
    layout = {i.id: i for i in planning.floor_items_raw(session, floor.id)}
    rows = {r.item_id: r for r in _rows(session, p, floor.id)}
    touched: set[str] = set()
    deleted: list[str] = []

    def put(iid: uuid.UUID, kind: str, fields: dict[str, Any], base: dict[str, Any]) -> None:
        row = rows.get(iid)
        if row is None:
            row = Change(
                project_id=p.id, floor_id=floor.id, item_id=iid, kind=kind, fields={}, base={}
            )
            session.add(row)
            rows[iid] = row
        row.kind, row.fields, row.base = kind, fields, base
        row.updated_at = datetime.now(UTC)

    def drop(iid: uuid.UUID) -> None:
        row = rows.pop(iid, None)
        if row is not None:
            session.delete(row)

    def as_is(iid: uuid.UUID, fields: dict[str, Any]) -> None:
        """Предмет расстановки: отличие от того, что было, — изменение; совпало — без него."""
        row = rows.get(iid)
        base = row.base if row is not None and row.base else _base(layout[iid])
        diff = {k: v for k, v in fields.items() if k in EDIT and base.get(k) != v}
        if diff:
            put(iid, "update", diff, base)
        else:
            drop(iid)

    for v in delete:
        iid = _uuid(v.get("id"))
        row = rows.get(iid) if iid else None
        if row is not None and row.kind == "add":
            drop(iid)  # type: ignore[arg-type]
        elif iid in layout:
            put(iid, "remove", {}, row.base if row is not None and row.base else _base(layout[iid]))  # type: ignore[index, arg-type]
        else:
            raise NotFound("Предмет не найден — возможно, его уже убрали. Обновите страницу.")
        deleted.append(str(iid))
    for v in sorted(create, key=lambda x: x.get("parent_id") is not None):
        iid = _uuid(v.get("id")) or uuid.uuid4()
        fields = _clean(v)
        if iid in layout:
            # вернуть убранное в проекте (отмена): каким было или с отличиями
            row = rows.get(iid)
            base = row.base if row is not None and row.base else _base(layout[iid])
            as_is(iid, {**base, **fields})
        else:
            type_id = _uuid(v.get("type_id"), "type_id")
            if type_id is None:
                raise AppError("Укажите тип предмета.", field="type_id")
            t = catalog.get_type(session, type_id)
            if t.archived_at is not None or t.layer_id is None:
                raise AppError(f"Тип «{t.name}» не ставится на план.")
            fields.setdefault("angle", 0.0)
            fields.setdefault("z", 0.0)
            fields.setdefault("label", "")
            fields.setdefault("params", {})
            put(
                iid,
                "add",
                {"type_id": str(t.id), "model_id": None, "parent_id": None, **fields},
                {},
            )
        touched.add(str(iid))
    for v in update:
        iid = _uuid(v.get("id"))
        row = rows.get(iid) if iid else None
        fields = _clean(v)
        if row is not None and row.kind == "add":
            put(iid, "add", {**row.fields, **fields}, {})  # type: ignore[arg-type]
        elif iid in layout:
            current = dict(row.fields) if row is not None and row.kind == "update" else {}
            base = row.base if row is not None and row.base else _base(layout[iid])  # type: ignore[index]
            as_is(iid, {**base, **current, **fields})  # type: ignore[arg-type]
        else:
            raise NotFound("Предмет не найден — возможно, его уже убрали. Обновите страницу.")
        touched.add(str(iid))
    p.updated_at = datetime.now(UTC)
    session.flush()
    # в журнал проекта, этажа и здания (9.2 п. 3, R-011); в историю предметов — нет: их
    # расстановка не менялась
    counts = (("поставлено", len(create)), ("изменено", len(update)), ("убрано", len(delete)))
    journal.record(
        session,
        actor,
        "project.change",
        f"Проект «{p.name}», «{floor.name}»: "
        + (", ".join(f"{what} {n}" for what, n in counts if n) or "без изменений"),
        entity=f"project:{p.id}",
        refs=[f"building:{p.building_id}", f"floor:{floor.id}"],
    )
    state = floor_state(session, actor, p, floor.id)
    return {
        "items": [i for i in state["items"] if i["id"] in touched],
        "deleted": deleted,
        "notes": [],
        "removed": state["removed"],
    }


# ---------------------------------------------------------------- спецификация (5.3.6 п. 5)


def specification(session: Session, actor: Actor, p: Project) -> dict[str, Any]:
    """Что нужно по проекту (новые предметы) по типам и моделям, сколько есть свободным на
    складе, сколько купить, цена (модели, иначе типа) и сумма."""
    need: Counter[tuple[str, str | None]] = Counter(
        (r.fields["type_id"], r.fields.get("model_id"))
        for r in _rows(session, p)
        if r.kind == "add" and r.fields.get("type_id")
    )
    types = catalog.types_by_id(session, [uuid.UUID(t) for t, _ in need])
    models = catalog.models_by_id(session, [uuid.UUID(m) for _, m in need if m])
    piece = [t for t in types.values() if t.accounting == "piece"]
    units = inventory.storage_units(session, [t.id for t in piece])
    linked = planning.items_of_units(session, [u.id for u in units])
    free_units = [u for u in units if u.id not in linked]
    stock = inventory.storage_stock(
        session, [t.id for t in types.values() if t.accounting == "quantity"]
    )
    used: Counter[uuid.UUID] = Counter()
    rows, total = [], Decimal(0)
    # сначала строки с моделью: им — единицы именно этой модели; без модели — любые
    for (type_id, model_id), count in sorted(need.items(), key=lambda x: x[0][1] is None):
        t = types[uuid.UUID(type_id)]
        m = models.get(uuid.UUID(model_id)) if model_id else None
        if t.accounting == "quantity":
            free = int(stock.get(t.id, Decimal(0)))
        else:
            fit = [
                u
                for u in free_units
                if u.type_id == t.id and (m is None or u.model_id == m.id) and u.id not in used
            ]
            free = len(fit)
            for u in fit[:count]:
                used[u.id] += 1
        have = min(count, free)
        buy = count - have
        price = Decimal(str((m.price if m and m.price is not None else t.price) or 0))
        amount = price * buy
        total += amount
        rows.append(
            {
                "type_id": t.id,
                "type": t.name,
                "model_id": m.id if m else None,
                "model": f"{m.manufacturer} {m.name}".strip() if m else "",
                "unit": t.unit,
                "need": count,
                "have": have,
                "buy": buy,
                "price": float(price),
                "sum": float(amount),
            }
        )
    rows.sort(key=lambda r: (r["type"], r["model"]))
    return {"rows": rows, "total": total}


# ---------------------------------------------------------------- сравнение (5.3.6 п. 4)


def compare(
    session: Session, actor: Actor, project_id: uuid.UUID, other_id: uuid.UUID | None
) -> dict[str, Any]:
    """Проект относительно расстановки или другого проекта: что добавлено, убрано,
    перемещено, изменено — по этажам и помещениям."""
    a = get_project(session, actor, project_id)
    b = get_project(session, actor, other_id) if other_id else None
    if b is not None and b.building_id != a.building_id:
        raise AppError("Сравнивать можно проекты одного здания.")
    floor_ids = {r.floor_id for r in _rows(session, a)} | (
        {r.floor_id for r in _rows(session, b)} if b else set()
    )
    floors = {f.id: f for f in building.floors(session, a.building_id)}
    rows = []
    counts: Counter[str] = Counter()
    for floor_id in sorted(floor_ids, key=lambda f: floors[f].elevation if f in floors else 0):
        mine = {i["id"]: i for i in floor_state(session, actor, a, floor_id)["items"]}
        if b is not None:
            theirs = {i["id"]: i for i in floor_state(session, actor, b, floor_id)["items"]}
        else:
            theirs = {
                str(i.id): _jsonable(planning.item_view(i))
                for i in planning.floor_items_raw(session, floor_id)
            }
        titles = {str(r.id): building.room_title(r) for r in building.live_rooms(session, floor_id)}
        types = catalog.types_by_id(
            session, [uuid.UUID(str(i["type_id"])) for i in [*mine.values(), *theirs.values()]]
        )
        for iid in sorted(set(mine) | set(theirs)):
            x, y = mine.get(iid), theirs.get(iid)
            if x and y:
                if any(x.get(k) != y.get(k) for k in POSITION):
                    what = "перемещён"
                elif any(x.get(k) != y.get(k) for k in EDIT):
                    what = "изменён"
                else:
                    continue
            else:
                what = "добавлен" if x else "убран"
            it = x or y
            assert it is not None
            counts[what] += 1
            rows.append(
                {
                    "floor_id": floor_id,
                    "floor": floors[floor_id].name if floor_id in floors else "",
                    "room": titles.get(str(it.get("room_id")), "вне помещений"),
                    "type": types[uuid.UUID(str(it["type_id"]))].name,
                    "what": what,
                    "item_id": iid,
                }
            )
    return {
        "a": a.name,
        "b": b.name if b else "Как есть",
        "rows": rows,
        "counts": dict(counts),
        "total_a": float(specification(session, actor, a)["total"]),
        "total_b": float(specification(session, actor, b)["total"]) if b else 0.0,
    }


# ---------------------------------------------------------------- применение (5.3.6 п. 7, 5.5)


def apply_plan(session: Session, actor: Actor, project_id: uuid.UUID) -> dict[str, Any]:
    """Что произойдёт при применении: новые предметы с подходящими единицами на складе (кого
    выдать) и что применить нельзя."""
    p = get_project(session, actor, project_id)
    rows = _rows(session, p)
    conflicts: list[dict[str, Any]] = []
    for floor_id in {r.floor_id for r in rows}:
        conflicts += floor_state(session, actor, p, floor_id)["conflicts"]
    adds = [r for r in rows if r.kind == "add"]
    types = catalog.types_by_id(session, [uuid.UUID(r.fields["type_id"]) for r in adds])
    units = inventory.storage_units(
        session, [t.id for t in types.values() if t.accounting == "piece"]
    )
    linked = planning.items_of_units(session, [u.id for u in units])
    free = [u for u in units if u.id not in linked]
    briefs = {b["id"]: b for b in inventory.unit_briefs(session, actor, free)}
    places = inventory.place_titles(session, actor, [u.place for u in free])
    floors = {f.id: f.name for f in building.floors(session, p.building_id)}
    taken: set[uuid.UUID] = set()
    out = []
    for r in adds:
        t = types[uuid.UUID(r.fields["type_id"])]
        model = r.fields.get("model_id")
        candidates = [u for u in free if u.type_id == t.id] if t.accounting == "piece" else []
        # своя модель — вперёд
        candidates.sort(key=lambda u: (str(u.model_id) != model, u.number))
        suggested = next((u.id for u in candidates if u.id not in taken), None)
        if suggested:
            taken.add(suggested)
        out.append(
            {
                "item_id": r.item_id,
                "floor": floors.get(r.floor_id, ""),
                "type": t.name,
                "accounting": t.accounting,
                "candidates": [
                    {**briefs[u.id], "place_title": places.get(u.place, "")}
                    for u in candidates[:30]
                ],
                "suggested": suggested,
            }
        )
    linked_removed = 0
    for r in rows:
        if r.kind == "remove":
            items = planning.items_by_id(session, [r.item_id])
            linked_removed += sum(1 for i in items.values() if i.unit_id)
    return {"items": out, "conflicts": conflicts, "linked_removed": linked_removed}


def apply_project(
    session: Session, actor: Actor, project_id: uuid.UUID, version: int, choices: dict[str, str]
) -> dict[str, Any]:
    """Перенести изменения в расстановку (одной транзакцией). Столкнувшиеся с расстановкой
    остаются в проекте с причиной. Новому предмету — выданная со склада единица (документ
    «Перемещение» проводит связь с учётом), «к закупке» или ничего."""
    p = get_project(session, actor, project_id)
    if p.version != version:
        raise stale("Проект")
    if p.archived_at:
        raise Conflict("Проект в архиве — его не применяют.")
    rows = _rows(session, p)
    if not rows:
        raise AppError("В проекте нет изменений.")
    notes: list[str] = []
    applied = 0
    kept = 0
    for floor_id in sorted({r.floor_id for r in rows}, key=str):
        state = floor_state(session, actor, p, floor_id)
        stuck = {c["item_id"] for c in state["conflicts"]}
        create, update, delete, done = [], [], [], []
        for r in _rows(session, p, floor_id):
            iid = str(r.item_id)
            if iid in stuck:
                kept += 1
                continue
            if r.kind == "add":
                fields = dict(r.fields)
                choice = choices.get(iid, "")
                if choice == "buy":
                    fields["params"] = {**(fields.get("params") or {}), "project.buy": True}
                elif choice:
                    fields["unit_id"] = choice
                create.append({"id": iid, **fields})
            elif r.kind == "update":
                update.append({"id": iid, **r.fields})
            else:
                delete.append({"id": iid})
            done.append(r)
        if create or update or delete:
            result = planning.apply_changes(
                session, actor, floor_id, planning.Changes(create, update, delete)
            )
            notes += result.get("notes", [])
        for r in done:
            session.delete(r)
        applied += len(done)
    p.version += 1
    p.updated_at = datetime.now(UTC)
    if not kept:
        p.applied_at = p.updated_at
    journal.record(
        session,
        actor,
        "project.apply",
        f"Применён проект «{p.name}»: изменений {applied}"
        + (f", осталось в проекте (столкнулись с расстановкой) {kept}" if kept else ""),
        entity=f"project:{p.id}",
        refs=[f"building:{p.building_id}"],
    )
    session.flush()
    return {"applied": applied, "kept": kept, "notes": notes}


def type_usage(session: Session, type_id: uuid.UUID | None, model_id: uuid.UUID | None) -> int:
    q = select(Change.fields).where(Change.kind == "add")
    n = 0
    for fields in session.scalars(q):
        if type_id is not None and fields.get("type_id") == str(type_id):
            n += 1
        elif model_id is not None and fields.get("model_id") == str(model_id):
            n += 1
    return n


def count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Project)) or 0


# ---------------------------------------------------------------- выгрузка (5.3.6 п. 6)

COLORS = {"added": "#2E7D32", "moved": "#EF6C00", "changed": "#1565C0", "removed": "#C62828"}
WHAT = {"added": "добавлен", "moved": "перемещён", "changed": "изменён", "removed": "убран"}


def _rect(it: dict[str, Any], t: Any) -> list[list[float]]:
    w, d = (t.width or 500), (t.depth or 500)
    a = math.radians(it.get("angle") or 0)
    ca, sa = math.cos(a), math.sin(a)
    x, y = it.get("x") or 0, it.get("y") or 0
    return [
        [x + dx * ca - dy * sa, y + dx * sa + dy * ca]
        for dx, dy in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))
    ]


def _money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def export_pdf(session: Session, actor: Actor, project_id: uuid.UUID) -> tuple[bytes, str]:
    """PDF для руководства: листы плана изменённых этажей (новое, перемещённое, убранное) и
    спецификация со сметой."""
    from weasyprint import HTML

    p = get_project(session, actor, project_id)
    b = building.get_building(session, actor, p.building_id)
    floors = {f.id: f for f in building.floors(session, p.building_id)}
    org = system.get(session, "organization_name")
    spec = specification(session, actor, p)
    pages = []
    for floor_id in sorted(
        {r.floor_id for r in _rows(session, p)}, key=lambda f: floors[f].elevation
    ):
        state = floor_state(session, actor, p, floor_id)
        changed = [i for i in state["items"] if i.get("state") and not i.get("parent_id")]
        types = catalog.types_by_id(
            session, [uuid.UUID(str(i["type_id"])) for i in [*changed, *state["removed"]]]
        )
        layout = {
            str(i.id): _jsonable(planning.item_view(i))
            for i in planning.floor_items_raw(session, floor_id)
        }
        overlays = []
        for it in state["removed"]:
            overlays.append(
                {
                    "points": _rect(it, types[uuid.UUID(str(it["type_id"]))]),
                    "fill": "none",
                    "stroke": COLORS["removed"],
                    "dash": True,
                }
            )
        for it in changed:
            t = types[uuid.UUID(str(it["type_id"]))]
            if it["state"] == "moved" and it["id"] in layout:
                overlays.append(
                    {
                        "points": _rect(layout[it["id"]], t),
                        "fill": "none",
                        "stroke": "#9E9E9E",
                        "dash": True,
                    }
                )
            overlays.append(
                {
                    "points": _rect(it, t),
                    "fill": COLORS[it["state"]],
                    "stroke": COLORS[it["state"]],
                    "opacity": 0.35,
                }
            )
        svg, scale = building.floor_svg(session, actor, floor_id, 277, 150, overlays)
        counts = Counter(i["state"] for i in [*changed, *state["removed"]])
        legend = " · ".join(
            f'<span style="color:{COLORS[k]}">■</span> {WHAT[k]}: {counts[k]}'
            for k in ("added", "moved", "changed", "removed")
            if counts[k]
        )
        conflicts = "".join(f"<li>{escape(c['text'])}</li>" for c in state["conflicts"])
        pages.append(
            f"""<section class="sheet"><h2>{escape(floors[floor_id].name)}</h2>
<div class="legend">{legend} · масштаб 1:{scale}</div><div class="draw">{svg}</div>
{f'<ul class="bad">{conflicts}</ul>' if conflicts else ""}</section>"""
        )
    spec_rows = "".join(
        f"<tr><td>{escape(r['type'])}</td><td>{escape(r['model'] or '—')}</td>"
        f"<td class='n'>{r['need']}</td><td class='n'>{r['have']}</td><td class='n'>{r['buy']}</td>"
        f"<td class='n'>{_money(r['price'])}</td><td class='n'>{_money(r['sum'])}</td></tr>"
        for r in spec["rows"]
    )
    head = "".join(
        f"<th>{h}</th>"
        for h in ("Тип", "Модель", "Нужно", "Есть на складе", "Купить", "Цена", "Сумма")
    )
    total = _money(float(spec["total"]))
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
@page {{ size: A4 landscape; margin: 10mm; }}
body {{ font-family: "DejaVu Sans", sans-serif; font-size: 9pt; margin: 0; }}
h1 {{ font-size: 14pt; margin: 0 0 2mm; }} h2 {{ font-size: 11pt; margin: 0 0 1mm; }}
.sheet {{ page-break-after: always; }} .legend {{ color: #444; margin-bottom: 1mm; }}
.draw {{ border: 0.3mm solid #999; height: 152mm; overflow: hidden; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 0.2mm solid #999; padding: 1mm 2mm; }}
th {{ background: #eee; text-align: left; }} .n {{ text-align: right; white-space: nowrap; }}
.bad {{ color: #C62828; }} .total td {{ font-weight: bold; }}
</style></head><body>
<h1>{escape(org) + " · " if org else ""}{escape(b.name)} — проект «{escape(p.name)}»</h1>
{"".join(pages)}
<section><h2>Спецификация и смета</h2><table>
<tr>{head}</tr>
{spec_rows or '<tr><td colspan="7">Новых предметов в проекте нет.</td></tr>'}
<tr class="total"><td colspan="6">Итого к закупке</td><td class="n">{total}</td></tr>
</table><p>{datetime.now():%d.%m.%Y}</p></section></body></html>"""
    return HTML(string=html).write_pdf(), f"{b.name} — {p.name}.pdf"


def export_xlsx(session: Session, actor: Actor, project_id: uuid.UUID) -> tuple[bytes, str]:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    p = get_project(session, actor, project_id)
    spec = specification(session, actor, p)
    wb = Workbook()
    ws = wb.active
    ws.title = "Спецификация"
    ws.append(["Тип", "Модель", "Ед.", "Нужно", "Есть на складе", "Купить", "Цена, ₽", "Сумма, ₽"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in spec["rows"]:
        ws.append(
            [r["type"], r["model"], r["unit"], r["need"], r["have"], r["buy"], r["price"], r["sum"]]
        )
    ws.append(["Итого к закупке", "", "", "", "", "", "", float(spec["total"])])
    ws[ws.max_row][0].font = Font(bold=True)
    for col, w in zip("ABCDEFGH", (34, 30, 8, 10, 16, 10, 14, 14), strict=True):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"{p.name} — спецификация.xlsx"
