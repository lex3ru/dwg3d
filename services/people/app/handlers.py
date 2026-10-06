"""Reactions to the events of other services."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit
from twin_chassis.bus import Bus

from .models import assignments


def register(bus: Bus) -> None:
    @bus.consumer("buildings.room.retired", name="room-retired")
    async def room_retired(session: AsyncSession, event: dict) -> None:
        """A room that is no more: its people are unassigned, each with an event (rights follow)."""
        room = UUID(event["data"]["room_id"])
        gone = (await session.execute(delete(assignments).where(assignments.c.room_id == room)
                                      .returning(assignments))).all()
        for a in gone:
            await emit(session, "people.person.unassigned", ("person", a.person_id),
                       {"person_id": str(a.person_id), "building_id": str(a.building_id), "floor_id": str(a.floor_id),
                        "room_id": str(room)},
                       building_id=a.building_id, floor_id=a.floor_id, room_id=room, person_id=a.person_id)

    @bus.consumer("assets.asset.retired", name="asset-retired")
    async def asset_retired(session: AsyncSession, event: dict) -> None:
        """A retired object is nobody's workplace."""
        asset = UUID(event["data"]["asset_id"])
        await session.execute(update(assignments).where(assignments.c.workplace_asset_id == asset)
                              .values(workplace_asset_id=None))
