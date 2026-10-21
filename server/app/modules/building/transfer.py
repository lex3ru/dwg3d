"""Перенос здания на другую установку: этажи с планами (стены, проёмы, колонны, лестницы,
подписи помещений, подложка) и лифты. Помещения на новой установке получаются, как всегда, из
плана при сохранении; по подписям с ключами исходных помещений строится соответствие «старое
помещение → новое»."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.modules.building import api
from app.modules.building.models import Lift
from app.modules.building.plan import Plan

LIFT_FIELDS = ("name", "x", "y", "w", "d", "angle", "door_side")


def export(
    session: Session, actor: Actor, building_id: uuid.UUID
) -> tuple[dict[str, Any], list[uuid.UUID], set[str]]:
    """Здание для пакета, id файлов (подложки) и назначения помещений, которые нужны."""
    b = api.get_building(session, actor, building_id)
    files: list[uuid.UUID] = []
    purposes: set[str] = set()
    floors = []
    for f in api.floors(session, b.id):
        plan = Plan.model_validate(f.plan or {}).model_dump()
        underlay = plan.get("underlay") or {}
        if underlay.get("file_id"):
            files.append(uuid.UUID(str(underlay["file_id"])))
        purposes |= {str(r["purpose_id"]) for r in plan.get("rooms", []) if r.get("purpose_id")}
        floors.append(
            {
                "key": str(f.id),
                "name": f.name,
                "elevation": f.elevation,
                "height": f.height,
                "plan": plan,
            }
        )
    lifts = [
        {
            **{k: getattr(lf, k) for k in LIFT_FIELDS},
            "floors": [str(x) for x in lf.floor_ids],
            "stops": [str(x) for x in lf.stop_ids],
        }
        for lf in session.scalars(select(Lift).where(Lift.building_id == b.id))
    ]
    return (
        {"name": b.name, "address": b.address, "floors": floors, "lifts": lifts},
        files,
        purposes,
    )


def load(
    session: Session,
    actor: Actor,
    data: dict[str, Any],
    name: str,
    purposes: dict[str, str | None],
    files: dict[str, uuid.UUID],
) -> dict[str, Any]:
    """Завести здание. Возвращает его id и соответствия ключей пакета: floors, rooms."""
    b = api.create_building(session, actor, name, data.get("address", ""))
    floors: dict[str, uuid.UUID] = {}
    rooms: dict[str, uuid.UUID] = {}
    for f in sorted(data.get("floors", []), key=lambda x: x["elevation"]):
        floor = api.add_floor(session, actor, b.id, f["name"], f["elevation"], f["height"])
        floors[f["key"]] = floor.id
        plan = dict(f["plan"])
        # подписи — новые помещения; ключ исходного помещения сохраняется в id подписи
        plan["rooms"] = [
            {
                **r,
                "id": f"new-{r['id']}",
                "purpose_id": purposes.get(str(r["purpose_id"])) if r.get("purpose_id") else None,
            }
            for r in plan.get("rooms", [])
        ]
        underlay = plan.get("underlay")
        if underlay and underlay.get("file_id"):
            new = files.get(str(underlay["file_id"]))
            plan["underlay"] = {**underlay, "file_id": str(new)} if new else None
        saved = api.save_plan(
            session, actor, floor.id, Plan.model_validate(plan), floor.plan_version, confirm=True
        )
        for label, room in saved.get("label_ids", {}).items():
            if label.startswith("new-"):
                rooms[label[4:]] = uuid.UUID(room)
    for lf in data.get("lifts", []):
        ids = [floors[k] for k in lf["floors"] if k in floors]
        if ids:
            api.create_lift(
                session,
                actor,
                b.id,
                {
                    **{k: lf[k] for k in LIFT_FIELDS if lf.get(k) is not None},
                    "floor_ids": ids,
                    "stop_ids": [floors[k] for k in lf["stops"] if k in floors],
                },
            )
    return {"building_id": b.id, "floors": floors, "rooms": rooms}
