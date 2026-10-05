"""Reactions to the events of the import service."""
from __future__ import annotations

import logging
import os
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit
from twin_chassis.bus import Bus
from twin_chassis.client import ServiceClient

from . import publish
from .models import buildings, drawings, floors, rooms

log = logging.getLogger("twin.buildings.handlers")


def register(bus: Bus, client: ServiceClient) -> None:
    async def building_of(session: AsyncSession, event: dict):
        """The building an event is about, if it is ours and alive."""
        return (await session.execute(select(buildings.c.id).where(
            buildings.c.id == UUID(event["building_id"]), buildings.c.deleted_at.is_(None)))).scalar_one_or_none()

    @bus.consumer("import.drawing.uploaded", name="drawing-uploaded")
    async def drawing_uploaded(session: AsyncSession, event: dict) -> None:
        if await building_of(session, event) is None:
            log.warning("a drawing was uploaded for an unknown building %s", event.get("building_id"))
            return
        data = event["data"]
        await session.execute(pg_insert(drawings).values(
            id=UUID(data["drawing_id"]), building_id=UUID(event["building_id"]), name=data["name"])
            .on_conflict_do_update(index_elements=["id"], set_={"name": data["name"], "updated_at": func.now()}))

    @bus.consumer("import.drawing.deleted", name="drawing-deleted")
    async def drawing_deleted(session: AsyncSession, event: dict) -> None:
        """The floors and rooms of a deleted drawing are retired, not deleted: others may refer to them."""
        drawing_id = UUID(event["data"]["drawing_id"])
        floor_ids = [i for (i,) in await session.execute(select(floors.c.id).where(floors.c.drawing_id == drawing_id))]
        if not floor_ids:
            await session.execute(drawings.delete().where(drawings.c.id == drawing_id))
            return
        gone = (await session.execute(update(rooms).where(rooms.c.floor_id.in_(floor_ids), rooms.c.status == "active")
                                      .values(status="retired", retired_at=func.now(), idx=None,
                                              version=rooms.c.version + 1)
                                      .returning(rooms.c.id, rooms.c.floor_id, rooms.c.building_id))).all()
        await session.execute(update(floors).where(floors.c.id.in_(floor_ids)).values(
            status="retired", candidate=None, version=floors.c.version + 1))
        await session.execute(update(drawings).where(drawings.c.id == drawing_id).values(
            build_id=None, result=None, updated_at=func.now()))
        for room_id, floor_id, building_id in gone:
            await emit(session, "buildings.room.retired", ("room", room_id),
                       {"room_id": str(room_id), "floor_id": str(floor_id)},
                       building_id=building_id, floor_id=floor_id, room_id=room_id)

    @bus.consumer("import.build.finished", name="build-finished")
    async def build_finished(session: AsyncSession, event: dict) -> None:
        """Fetch the result of the build and make it the state of the building."""
        data = event["data"]
        if await building_of(session, event) is None:
            return
        drawing_id = UUID(data["drawing_id"])
        await session.execute(pg_insert(drawings).values(id=drawing_id, building_id=UUID(event["building_id"]))
                              .on_conflict_do_nothing())
        drawing = (await session.execute(select(drawings).where(drawings.c.id == drawing_id).with_for_update())).one()
        if drawing.build_n >= data["n"]:
            return                                  # an older build arriving late
        r = await client.get("import", f"/builds/{data['build_id']}/result")
        if r.status_code == 404:
            log.warning("build %s is gone from import", data["build_id"])
            return
        r.raise_for_status()                        # anything else: the event is redelivered later
        body = r.json()
        result, plans = body["result"], {}
        for f in result.get("floors") or []:
            if f.get("plan"):
                p = await client.get("import", f"/builds/{data['build_id']}/files/{f['plan']}")
                p.raise_for_status()
                plans[f["id"]] = p.json()
        summary = await publish.publish(session, drawing, body["build"], result, plans)
        log.info("build %s published: %s", data["build_id"], {k: {a: len(b) for a, b in v.items()}
                                                              for k, v in summary.items()})


def services() -> dict[str, str]:
    from twin_chassis.client import services_from_env
    return services_from_env(os.environ.get("TWIN_SERVICES", "import=http://import:8000"))
