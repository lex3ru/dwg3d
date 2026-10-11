"""Reactions to the events of the import service."""
from __future__ import annotations

import logging
import os
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit, uuid7
from twin_chassis.bus import Bus
from twin_chassis.client import ServiceClient

from . import publish
from .models import buildings, drawings, floors, revisions, rooms

log = logging.getLogger("twin.buildings.handlers")


def register(bus: Bus, client: ServiceClient) -> None:
    async def building_of(session: AsyncSession, event: dict):
        """The building an event is about, if it is ours and alive."""
        return (await session.execute(select(buildings.c.id).where(
            buildings.c.id == UUID(event["building_id"]), buildings.c.deleted_at.is_(None)))).scalar_one_or_none()

    async def drawing_came(session: AsyncSession, event: dict) -> None:
        if await building_of(session, event) is None:
            log.warning("a drawing came for an unknown building %s", event.get("building_id"))
            return
        data = event["data"]
        await session.execute(pg_insert(drawings).values(
            id=UUID(data["drawing_id"]), building_id=UUID(event["building_id"]), name=data["name"])
            .on_conflict_do_update(index_elements=["id"], set_={"name": data["name"], "updated_at": func.now()}))

    @bus.consumer("import.drawing.uploaded", name="drawing-uploaded")
    async def drawing_uploaded(session: AsyncSession, event: dict) -> None:
        await drawing_came(session, event)

    @bus.consumer("import.drawing.drawn", name="drawing-drawn")
    async def drawing_drawn(session: AsyncSession, event: dict) -> None:
        """A plan drawn in the 2D editor: a drawing like an uploaded one, its builds come the same way."""
        await drawing_came(session, event)

    @bus.consumer("import.drawing.renamed", name="drawing-renamed")
    async def drawing_renamed(session: AsyncSession, event: dict) -> None:
        await session.execute(update(drawings).where(drawings.c.id == UUID(event["data"]["drawing_id"]))
                              .values(name=event["data"]["name"], updated_at=func.now()))

    @bus.consumer("import.drawing.deleted", name="drawing-deleted")
    async def drawing_deleted(session: AsyncSession, event: dict) -> None:
        """The floors and rooms of a deleted drawing are retired, not deleted: others may refer to them."""
        drawing_id = UUID(event["data"]["drawing_id"])
        await session.execute(update(revisions).where(
            revisions.c.drawing_id == drawing_id, revisions.c.status == "draft").values(
            status="discarded", proposal=None, result=None, plans=None, decided_by="deleted"))
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
        latest = (await session.execute(select(func.max(revisions.c.n))
                                        .where(revisions.c.drawing_id == drawing_id))).scalar()
        if max(drawing.build_n, latest or 0) >= data["n"]:
            return                                  # an older build arriving late, or this one again
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
        if drawing.build_id is None:                # the first build of the drawing is the building at once
            summary = await publish.publish(session, drawing, body["build"], result, plans)
            log.info("build %s published", data["build_id"])
            return
        proposal = await publish.propose(session, drawing, result, plans)
        explained = await publish.explain(session, drawing, plans, proposal)
        if publish.loses_nothing(explained):        # only adds and keeps: nobody needs to look first
            revision_id = uuid7()
            summary = await publish.apply(session, drawing, body["build"], result, plans, proposal, revision_id)
            await session.execute(insert(revisions).values(
                id=revision_id, building_id=drawing.building_id, drawing_id=drawing_id,
                build_id=UUID(data["build_id"]), n=data["n"], status="published", summary=summary,
                published_at=func.now(), decided_by="auto"))
            log.info("build %s published: it retires nothing", data["build_id"])
            return
        # it would retire rooms or floors: a draft for the administrator; an older draft gives way
        await session.execute(update(revisions).where(
            revisions.c.drawing_id == drawing_id, revisions.c.status == "draft").values(
            status="discarded", proposal=None, result=None, plans=None, decided_by="superseded"))
        revision_id = uuid7()
        await session.execute(insert(revisions).values(
            id=revision_id, building_id=drawing.building_id, drawing_id=drawing_id, build_id=UUID(data["build_id"]),
            n=data["n"], status="draft", summary=explained["count"], proposal=proposal, result=result, plans=plans))
        await emit(session, "buildings.revision.drafted", ("revision", revision_id),
                   {"revision_id": str(revision_id), "drawing_id": str(drawing_id), "build_id": data["build_id"],
                    "count": explained["count"]}, building_id=drawing.building_id)
        log.info("build %s waits as a draft: %s", data["build_id"], explained["count"])


def services() -> dict[str, str]:
    from twin_chassis.client import services_from_env
    return services_from_env(os.environ.get("TWIN_SERVICES", "import=http://import:8000,access=http://access:8000,assets=http://assets:8000"))
