"""Перенос здания на другую установку: предметы расстановки по этажам — тип, модель, точка,
поворот, высота, подпись, параметры расчётов, вложение и связь с инвентарной единицей.
Ставятся теми же изменениями, что из редактора (apply_changes): помещение предмета
определяется по плану, связь с единицей — через link."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.modules.building import api as building
from app.modules.planning import api


def export(session: Session, actor: Actor, building_id: uuid.UUID) -> list[dict[str, Any]]:
    out = []
    for f in building.floors(session, building_id):
        for i in api.floor_items_raw(session, f.id):
            out.append(
                {
                    "key": str(i.id),
                    "floor": str(f.id),
                    "type": str(i.type_id),
                    "model": str(i.model_id) if i.model_id else None,
                    "parent": str(i.parent_id) if i.parent_id else None,
                    "x": i.x,
                    "y": i.y,
                    "angle": i.angle,
                    "z": i.z,
                    "label": i.label,
                    "params": i.params or {},
                    "unit": str(i.unit_id) if i.unit_id else None,
                }
            )
    return out


def load(
    session: Session,
    actor: Actor,
    items: list[dict[str, Any]],
    floors: dict[str, uuid.UUID],
    types: dict[str, uuid.UUID | None],
    models: dict[str, uuid.UUID | None],
    units: dict[str, uuid.UUID],
) -> int:
    """Поставить предметы; вместилища — раньше вложенного. Тип не нашёлся — предмет не ставится
    (о таком говорит проверка пакета)."""
    ids = {i["key"]: uuid.uuid4() for i in items}
    by_floor: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for i in sorted(items, key=lambda x: x["parent"] is not None):
        floor = floors.get(i["floor"])
        type_id = types.get(i["type"])
        if floor is None or type_id is None:
            continue
        by_floor.setdefault(floor, []).append(
            {
                "id": str(ids[i["key"]]),
                "type_id": str(type_id),
                "model_id": str(models[i["model"]])
                if i.get("model") and models.get(i["model"])
                else None,
                "parent_id": str(ids[i["parent"]]) if i.get("parent") in ids else None,
                **({"x": i["x"], "y": i["y"]} if not i.get("parent") else {}),
                "angle": i.get("angle") or 0,
                "z": i.get("z") or 0,
                "label": i.get("label") or "",
                "params": i.get("params") or {},
                "unit_id": str(units[i["unit"]]) if i.get("unit") in units else None,
            }
        )
    done = 0
    for floor, create in by_floor.items():
        api.apply_changes(session, actor, floor, api.Changes(create=create))
        done += len(create)
    return done
