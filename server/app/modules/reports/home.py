"""Главная администратора (6.5.1): «Требует внимания» — счётчики со ссылками в
отфильтрованные списки, стоимость имущества здания, последние документы, быстрые действия.
Учётные счётчики считаются сразу; то, что требует расчёта по этажам (неразмещённые,
расхождения, освещённость, устаревшие проекты), — отдельным запросом."""

import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import Forbidden
from app.modules.building import api as building
from app.modules.calc import api as calc
from app.modules.inventory import api as inventory
from app.modules.link import api as link
from app.modules.projects import api as projects


def _admin(actor: Actor) -> None:
    if not actor.is_admin:
        raise Forbidden()


def summary(session: Session, actor: Actor, building_id: uuid.UUID) -> dict[str, Any]:
    _admin(actor)
    b = building.get_building(session, actor, building_id)
    q = f"building_id={b.id}"
    cost = inventory.cost_statement(session, actor, date.today(), ["building"], b.id)["total"]
    return {
        "building": {"id": b.id, "name": b.name},
        "attention": [
            {
                "key": "broken",
                "title": "Неисправные",
                "count": inventory.counts_with_state(session, ["broken"], b.id),
                "href": f"/property?state=broken&{q}",
            },
            {
                "key": "repair",
                "title": "В ремонте",
                "count": inventory.counts_with_state(session, ["repair"], b.id),
                "href": f"/property?state=repair&{q}",
            },
            {
                "key": "not_found",
                "title": "Не найдены при инвентаризации",
                "count": inventory.counts_with_state(session, ["not_found"], b.id),
                "href": f"/property?state=not_found&{q}",
            },
        ],
        "cost": {"initial": cost["initial"], "value": cost["value"], "units": cost["units"]},
        "documents": [
            {
                "id": d["id"],
                "title": d["title"],
                "date": d["date"],
                "status": d["status"],
                "kind": d["kind"],
            }
            for d in inventory.latest_documents(session, actor)
        ],
    }


def plan_checks(session: Session, actor: Actor, building_id: uuid.UUID) -> dict[str, Any]:
    """Счётчики, которые требуют расчёта по этажам."""
    _admin(actor)
    b = building.get_building(session, actor, building_id)
    unplaced = mismatch = dark = 0
    first_unplaced = first_dark = None
    for f in building.floors(session, b.id):
        view = link.floor_view(session, actor, f.id)
        if view["unplaced"] and first_unplaced is None:
            first_unplaced = f.id
        unplaced += len(view["unplaced"])
        mismatch += len(view["mismatch"])
        light = calc.run(session, actor, "light", f.id, None, {})
        low = len((light.get("issues") or {}).get("rows") or [])
        if low and first_dark is None:
            first_dark = f.id
        dark += low
    outdated = [
        p
        for p in projects.projects(session, actor, b.id)
        if projects.project_view(session, actor, p)["status"] == "outdated"
    ]
    return {
        "attention": [
            {
                "key": "unplaced",
                "title": "Неразмещённые",
                "count": unplaced,
                "href": f"/plan/{b.id}/{first_unplaced}?mode=place"
                if first_unplaced
                else f"/plan/{b.id}",
            },
            {
                "key": "dark",
                "title": "Помещения с освещённостью ниже нормы",
                "count": dark,
                "href": f"/plan/{b.id}/{first_dark}?mode=place&calc=light"
                if first_dark
                else f"/plan/{b.id}",
            },
            {
                "key": "mismatch",
                "title": "Расхождения плана и учёта",
                "count": mismatch,
                "href": f"/reports?report=mismatch&building_id={b.id}",
            },
            {
                "key": "outdated",
                "title": "Устаревшие проекты",
                "count": len(outdated),
                "href": f"/projects?building={b.id}",
            },
        ]
    }
