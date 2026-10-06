"""Every event of the bus is kept as it came. The handler runs in one transaction with
the record «this event is handled», so a redelivery adds nothing; the durable
subscription keeps what happened while the journal was down."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis.bus import Bus

from .models import events

SCOPE = ("building_id", "floor_id", "room_id", "asset_id", "person_id")


def row_of(event: dict) -> dict:
    actor = event.get("actor") or {}
    return {"id": UUID(event["id"]), "type": event["type"], "time": datetime.fromisoformat(event["time"]),
            "actor_kind": actor.get("kind", "service"), "actor_id": str(actor.get("id", "")),
            "actor_person_id": UUID(actor["person_id"]) if actor.get("person_id") else None,
            "subject_kind": event["subject"]["kind"], "subject_id": str(event["subject"]["id"]),
            "data": event.get("data") or {}, **{k: UUID(event[k]) if event.get(k) else None for k in SCOPE}}


def register(bus: Bus) -> None:
    @bus.consumer(">", name="journal")
    async def keep(session: AsyncSession, event: dict) -> None:
        await session.execute(pg_insert(events).values(**row_of(event)).on_conflict_do_nothing(index_elements=["id"]))
