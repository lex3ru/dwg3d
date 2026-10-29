"""Стоимость имущества на дату (5.4.5 п. 4, С19): первоначальная и остаточная, с разбивкой
по зданию, этажу, месту, слою, типу, подразделению. На экране «Стоимость» ведомость считается
фоновой задачей (8.2: «идёт в фоне», R-036, ADR-0021); отчёты берут statement напрямую."""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import tasks
from app.core.actor import Actor
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.modules.access import api as access
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.inventory.models import StockMove, Unit
from app.modules.inventory.places import Places
from app.modules.inventory.rules import residual
from app.modules.inventory.units import events_at

GROUPS = {
    "building": "Здание",
    "floor": "Этаж",
    "place": "Место хранения",
    "layer": "Слой",
    "type": "Тип",
    "department": "Подразделение",
}
TASK = "inventory.cost_statement"


def _check(actor: Actor, group_by: list[str]) -> None:
    if not actor.sees_cost:
        raise Forbidden()
    for g in group_by:
        if g not in GROUPS:
            raise AppError(f"Неизвестная разбивка «{g}».", field="group_by")


def start(
    session: Session,
    actor: Actor,
    at: date,
    group_by: list[str],
    building_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Поставить ведомость в очередь: ошибки запроса — сразу, счёт — у обработчика задач, а
    не в процессе приложения, где 50 000 единиц держали соединение и память (8.1, R-036).
    Такая же, пока прежняя считается, — та же задача."""
    _check(actor, group_by)
    if building_id is not None:
        building.get_building(session, actor, building_id)
    payload = {
        "at": at.isoformat(),
        "group_by": group_by,
        "building_id": str(building_id) if building_id else None,
        "user_id": str(actor.user_id),
    }
    return tasks.enqueue_once(session, TASK, payload, actor)


@tasks.task(TASK, "Ведомость стоимости", timeout=timedelta(minutes=10))
def run(session: Session, payload: dict[str, Any], _progress: tasks.Progress) -> dict[str, Any]:
    actor = access.actor_of(access.get(session, uuid.UUID(payload["user_id"])))
    building_id = payload.get("building_id")
    st = statement(session, actor, date.fromisoformat(payload["at"]), payload["group_by"],
                   uuid.UUID(building_id) if building_id else None)
    return {**st, "at": st["at"].isoformat()}


def result(session: Session, actor: Actor, job_id: uuid.UUID) -> dict[str, Any]:
    """Посчитанная ведомость по ключу задачи — для Excel."""
    if not actor.sees_cost:
        raise Forbidden()
    job = session.get(tasks.Job, job_id)
    if job is None or job.kind != TASK:
        raise NotFound("Ведомость не найдена.")
    if job.status != "done" or job.result is None:
        raise Conflict("Ведомость ещё не посчитана.", code="not_ready")
    return {**job.result, "at": date.fromisoformat(job.result["at"])}


def statement(
    session: Session,
    actor: Actor,
    at: date,
    group_by: list[str],
    building_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    _check(actor, group_by)
    places = Places(session, actor)
    layers = catalog.layer_names(session)
    buildings: dict[uuid.UUID | None, str] = {None: "вне зданий"}
    floors: dict[uuid.UUID | None, str] = {None: "—"}

    def building_name(bid: uuid.UUID | None) -> str:
        if bid not in buildings:
            buildings[bid] = building.get_building(session, actor, bid).name  # type: ignore[arg-type]
        return buildings[bid]

    def floor_name(fid: uuid.UUID | None) -> str:
        if fid not in floors:
            floors[fid] = building.get_floor(session, actor, fid).name  # type: ignore[arg-type]
        return floors[fid]

    units = list(session.scalars(select(Unit).where(Unit.commissioned_on <= at)))
    snaps = events_at(session, select(Unit.id).where(Unit.commissioned_on <= at), at)
    if "place" in group_by:
        places.preload(e.place for e in snaps.values())
    types = catalog.types_by_id(session, [u.type_id for u in units])
    groups: dict[tuple[str, ...], dict[str, Any]] = defaultdict(
        lambda: {"units": 0, "qty_items": 0, "initial": Decimal(0), "value": Decimal(0)}
    )

    def key_of(
        bid: Any, fid: Any, place: str, type_id: uuid.UUID, department: str
    ) -> tuple[str, ...]:
        t = types.get(type_id) or catalog.get_type(session, type_id)
        types[type_id] = t
        # только запрошенные разбивки: название места на 50 000 единиц дорого (8.1)
        values = {
            "building": lambda: building_name(bid),
            "floor": lambda: floor_name(fid),
            "place": lambda: places.title(place),
            "layer": lambda: layers.get(t.layer_id, "без слоя") if t.layer_id else "без слоя",
            "type": lambda: t.name,
            "department": lambda: department or "—",
        }
        return tuple(values[g]() for g in group_by)

    for u in units:
        snap = snaps.get(u.id)
        if snap is None or snap.state == "written_off":
            continue
        if building_id and snap.building_id != building_id:
            continue
        if snap.building_id and not actor.can_see_building(snap.building_id):
            continue
        k = key_of(snap.building_id, snap.floor_id, snap.place, u.type_id, u.department)
        g = groups[k]
        g["units"] += 1
        g["initial"] += Decimal(str(u.price or 0))
        g["value"] += Decimal(
            str(
                residual(
                    u.price, u.commissioned_on, u.life_months, snap.value_base, snap.value_date, at
                )
            )
        )
    # остатки — по средней цене, стоимость не убывает
    q = (
        select(
            StockMove.place,
            StockMove.building_id,
            StockMove.floor_id,
            StockMove.type_id,
            func.sum(StockMove.qty),
            func.sum(StockMove.amount),
        )
        .where(StockMove.date <= at)
        .group_by(StockMove.place, StockMove.building_id, StockMove.floor_id, StockMove.type_id)
    )
    if building_id:
        q = q.where(StockMove.building_id == building_id)
    for place, bid, fid, type_id, qty, amount in session.execute(q).all():
        if not qty or qty <= 0:
            continue
        k = key_of(bid, fid, place, type_id, "")
        g = groups[k]
        g["qty_items"] += 1
        g["initial"] += Decimal(amount)
        g["value"] += Decimal(amount)
    rows = [
        {
            "group": list(k),
            "units": g["units"],
            "stock_positions": g["qty_items"],
            "initial": float(g["initial"]),
            "value": float(g["value"]),
        }
        for k, g in sorted(groups.items())
    ]
    return {
        "at": at,
        "group_by": group_by,
        "group_titles": [GROUPS[g] for g in group_by],
        "rows": rows,
        "total": {
            "units": sum(r["units"] for r in rows),
            "initial": round(sum(r["initial"] for r in rows), 2),
            "value": round(sum(r["value"] for r in rows), 2),
        },
    }
