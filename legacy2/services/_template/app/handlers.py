"""Reactions to events. A handler runs in one transaction with the record
"this event is handled", so a redelivered event does nothing."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis.bus import Bus

from .models import notes


def register(bus: Bus) -> None:
    @bus.consumer("__service__.note.created", name="echo")
    async def echo(session: AsyncSession, event: dict) -> None:
        """The sample handler: the service hears its own event and marks the note."""
        await session.execute(update(notes).where(notes.c.id == UUID(event["subject"]["id"]))
                              .values(echoed_at=func.now(), echoes=notes.c.echoes + 1))
