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
