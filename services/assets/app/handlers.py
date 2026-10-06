"""Reactions to the events of other services: the copies kept here follow their owners."""
from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit
from twin_chassis.bus import Bus
from twin_chassis.client import ServiceClient

from . import core
from .models import assets

log = logging.getLogger("twin.assets.handlers")


def register(bus: Bus, client: ServiceClient) -> None:
    async def refresh(session: AsyncSession, type_id: UUID) -> None:
        """Take the type from the catalog anew and re-check the objects of it against the schema."""
        kind = await core.store_schema(session, await core.fetch_type(client, type_id, None))
        rows = (await session.execute(select(assets).where(assets.c.type_id == type_id, assets.c.state != "retired")
                                      .with_for_update())).all()
        for a in rows:
            flag = core.incomplete(kind.schema, a.props)
            values = {"type_name": kind.name, "category_id": kind.category_id, "schema_version": kind.schema_version,
                      "needs_fill": flag}
            if any(getattr(a, k) != v for k, v in values.items()):
                await session.execute(update(assets).where(assets.c.id == a.id).values(**values, updated_at=func.now()))
                if flag != a.needs_fill:
                    await core.record(session, a.id, core.SYSTEM, "system", {"needs_fill": [a.needs_fill, flag]},
                                      reason="Изменилась схема свойств типа в каталоге")
                    await emit(session, "assets.asset.changed", ("asset", a.id),
                               {"asset_id": str(a.id), "fields": ["needs_fill"]}, **core.scope_fields(a))

    @bus.consumer("catalog.type.*", name="type-changed")
    async def type_changed(session: AsyncSession, event: dict) -> None:
        await refresh(session, UUID(event["data"]["type_id"]))

    @bus.consumer("catalog.property_set.changed", name="set-changed")
    async def set_changed(session: AsyncSession, event: dict) -> None:
        for type_id in event["data"]["type_ids"]:
            await refresh(session, UUID(type_id))

    @bus.consumer("buildings.room.retired", name="room-retired")
    async def room_retired(session: AsyncSession, event: dict) -> None:
        """The room is gone from the building: what stood in it stays attached to it, to be placed anew."""
        rows = (await session.execute(update(assets).where(
            assets.c.room_id == UUID(event["data"]["room_id"]), assets.c.state != "retired",
            assets.c.needs_placement.is_(False)).values(needs_placement=True, version=assets.c.version + 1,
                                                        updated_at=func.now()).returning(assets))).all()
        for a in rows:
            await core.record(session, a.id, core.SYSTEM, "system", {"needs_placement": [False, True]},
                              reason="Помещение снято в новой версии чертежа")
            await emit(session, "assets.asset.changed", ("asset", a.id),
                       {"asset_id": str(a.id), "fields": ["needs_placement"]}, **core.scope_fields(a))

    async def rehouse(session: AsyncSession, a, room: UUID | None, reason: str) -> None:
        """The object stays where it stands; which room that is has changed. No room — it waits to be placed."""
        if room is None:
            if a.needs_placement:
                return
            await session.execute(update(assets).where(assets.c.id == a.id).values(
                needs_placement=True, version=assets.c.version + 1, updated_at=func.now()))
            await core.record(session, a.id, core.SYSTEM, "system", {"needs_placement": [False, True]}, reason=reason)
            await emit(session, "assets.asset.changed", ("asset", a.id),
                       {"asset_id": str(a.id), "fields": ["needs_placement"]}, **core.scope_fields(a))
            return
        if room == a.room_id and not a.needs_placement:
            return
        moved = (await session.execute(update(assets).where(
            (assets.c.id == a.id) | (assets.c.container_id == a.id)).values(
            room_id=room, needs_placement=False, version=assets.c.version + 1, updated_at=func.now())
            .returning(assets))).all()
        changes = {"room_id": [str(a.room_id), str(room)]} if room != a.room_id else {"needs_placement": [True, False]}
        await core.record(session, a.id, core.SYSTEM, "moved", changes, reason=reason)
        for m in moved:
            await emit(session, "assets.asset.moved", ("asset", m.id),
                       {"asset_id": str(m.id), "from_room_id": str(a.room_id), "to_room_id": str(room),
                        "from_building_id": str(a.building_id)}, **core.scope_fields(m))

    async def relocate(session: AsyncSession, floor_id: UUID, where, reason: str) -> None:
        """Ask the buildings service which room each object's point is in now."""
        rows = (await session.execute(select(assets).where(
            assets.c.floor_id == floor_id, assets.c.x.is_not(None), assets.c.state != "retired", where)
            .order_by(assets.c.id).with_for_update())).all()
        if not rows:
            return
        r = await client.request("POST", "buildings", f"/floors/{floor_id}/locate",
                                 json={"points": [[a.x, a.y] for a in rows]})
        if r.status_code == 404:
            for a in rows:                                       # the floor is gone: everything on it waits
                await rehouse(session, a, None, reason)
            return
        r.raise_for_status()                                     # anything else: the event comes again later
        for a, room in zip(rows, r.json()["rooms"], strict=True):
            await rehouse(session, a, UUID(room) if room else None, reason)

    @bus.consumer("buildings.revision.published", name="revision-published")
    async def revision_published(session: AsyncSession, event: dict) -> None:
        """A new revision of a drawing: rooms split, gone, reshaped — every object finds its room by its point."""
        rooms, floors, moves = event["data"]["rooms"], event["data"]["floors"], event["data"].get("moves") or {}
        for floor_id, (dx, dy) in moves.items():        # the floor is aligned differently: points move with it
            await session.execute(update(assets).where(assets.c.floor_id == UUID(floor_id), assets.c.x.is_not(None))
                                  .values(x=assets.c.x + dx, y=assets.c.y + dy, updated_at=func.now()))
        if not (moves or rooms["created"] or rooms["retired"] or any(c.get("outline") for c in rooms["changed"])):
            return
        for floor_id in floors["active"]:
            await relocate(session, UUID(floor_id), assets.c.id.is_not(None), "Помещение уточнено по новой версии чертежа")
        for floor_id in floors["retired"]:
            await relocate(session, UUID(floor_id), assets.c.id.is_not(None), "Этаж снят в новой версии чертежа")

    @bus.consumer("buildings.room.split", name="room-split")
    async def room_split(session: AsyncSession, event: dict) -> None:
        d = event["data"]
        await relocate(session, UUID(d["floor_id"]), assets.c.room_id == UUID(d["from"]), "Помещение разделено")

    @bus.consumer("buildings.room.merged", name="room-merged")
    async def room_merged(session: AsyncSession, event: dict) -> None:
        """What stood in the merged rooms stands in the heir."""
        d = event["data"]
        rows = (await session.execute(select(assets).where(
            assets.c.room_id.in_([UUID(x) for x in d["from"]]), assets.c.container_id.is_(None)).with_for_update())).all()
        for a in rows:
            await rehouse(session, a, UUID(d["into"]), "Помещения объединены")

    @bus.consumer("people.person.left", name="person-left")
    async def person_left(session: AsyncSession, event: dict) -> None:
        """Someone who left answers for nothing."""
        person = UUID(event["data"]["person_id"])
        rows = (await session.execute(update(assets).where(assets.c.responsible_id == person).values(
            responsible_id=None, version=assets.c.version + 1, updated_at=func.now()).returning(assets))).all()
        for a in rows:
            await core.record(session, a.id, core.SYSTEM, "system", {"responsible_id": [str(person), None]},
                              reason="Ответственный выбыл")
            await emit(session, "assets.asset.responsible_changed", ("asset", a.id),
                       {"asset_id": str(a.id), "from": str(person), "to": None}, **core.scope_fields(a))
