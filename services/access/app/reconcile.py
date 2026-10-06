"""The automatic grants checked against their sources: assignments of people to rooms
(the people service) and who answers for which object (the assets service). What
is missing is given, what has no source any more is revoked — so a lost or
mishandled event does no lasting harm. Runs on start and every TWIN_RECONCILE_S
seconds (default 600), and on `POST /reconcile`."""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from twin_chassis import Problem
from twin_chassis.client import ServiceClient

from .handlers import give, revoke
from .models import grants

log = logging.getLogger("twin.access")
Key = tuple[UUID, str, str, UUID, str]          # person, role, scope kind, scope id, origin


async def _wanted(client: ServiceClient) -> dict[Key, UUID]:
    """The automatic grants there should be, each with its building."""
    out: dict[Key, UUID] = {}
    sources = (("people", "/assignments",
                lambda a: (a["person_id"], "viewer", "room", a["room_id"], "assignment", a["building_id"])),
               ("assets", "/responsibles",
                lambda a: (a["person_id"], "responsible", "asset", a["asset_id"], "responsible", a["building_id"])))
    for service, path, make in sources:
        r = await client.request("GET", service, path)
        if r.status_code != 200:
            raise Problem(503, "service_unavailable", f"Сервис «{service}» не ответил — сверка не выполнена",
                          extra={"service": service})
        for item in r.json()["items"]:
            person, role, kind, scope, origin, building = make(item)
            out[(UUID(person), role, kind, UUID(scope), origin)] = UUID(building)
    return out


async def reconcile(db, client: ServiceClient) -> dict:
    wanted = await _wanted(client)
    added = removed = 0
    async with db.begin() as session:
        rows = (await session.execute(select(grants).where(grants.c.origin.in_(("assignment", "responsible"))))).all()
        have = {(g.person_id, g.role, g.scope_kind, g.scope_id, g.origin): g for g in rows}
        for key, g in have.items():
            if key not in wanted:
                removed += await revoke(session, grants.c.id == g.id)
        for key, building in wanted.items():
            if key not in have:
                person, role, kind, scope, origin = key
                added += await give(session, person, role, kind, scope, building, origin, "reconcile")
    if added or removed:
        log.info("reconciled automatic grants: %d added, %d removed", added, removed)
    return {"added": added, "removed": removed}
