"""Reactions to the events of the people service."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit
from twin_chassis.bus import Bus

from .models import grants, subjects
from .routes import grant_event


def register(bus: Bus) -> None:
    @bus.consumer("people.person.linked", name="person-linked")
    async def linked(session: AsyncSession, event: dict) -> None:
        """Which account is which person: rights are given to people, an account acts as its person."""
        sub, person = event["data"]["user_sub"], UUID(event["data"]["person_id"])
        await session.execute(delete(subjects).where((subjects.c.user_sub == sub) | (subjects.c.person_id == person)))
        await session.execute(pg_insert(subjects).values(user_sub=sub, person_id=person))

    @bus.consumer("people.person.unlinked", name="person-unlinked")
    async def unlinked(session: AsyncSession, event: dict) -> None:
        await session.execute(delete(subjects).where(subjects.c.person_id == UUID(event["data"]["person_id"])))

    @bus.consumer("people.person.left", name="person-left")
    async def left(session: AsyncSession, event: dict) -> None:
        """Someone who left has no rights, whatever was given."""
        person = UUID(event["data"]["person_id"])
        gone = (await session.execute(delete(grants).where(grants.c.person_id == person).returning(grants))).all()
        await session.execute(delete(subjects).where(subjects.c.person_id == person))
        for g in gone:
            await emit(session, "access.grant.revoked", ("grant", g.id), grant_event(g),
                       building_id=g.building_id, person_id=g.person_id)
