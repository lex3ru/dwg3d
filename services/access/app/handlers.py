"""Reactions to the events of the people, assets and buildings services: the automatic grants
(docs/CONTRACTS.md, section 2) follow what happens there; `reconcile.py` is the safety net."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit, uuid7
from twin_chassis.bus import Bus

from .models import grants, subjects
from .routes import grant_event


async def revoke(session: AsyncSession, *where) -> int:
    """Delete the grants matching `where`, an event for each; returns how many."""
    gone = (await session.execute(delete(grants).where(*where).returning(grants))).all()
    for g in gone:
        await emit(session, "access.grant.revoked", ("grant", g.id), grant_event(g),
                   building_id=g.building_id, person_id=g.person_id)
    return len(gone)


async def give(session: AsyncSession, person_id: UUID, role: str, kind: str, scope_id: UUID, building_id: UUID,
               origin: str, by: str) -> bool:
    """An automatic grant, unless it is there already; returns whether it was added."""
    g = (await session.execute(pg_insert(grants).values(
        id=uuid7(), person_id=person_id, role=role, scope_kind=kind, scope_id=scope_id, building_id=building_id,
        origin=origin, created_by=by).on_conflict_do_nothing(constraint="uq_grants_once").returning(grants))
         ).one_or_none()
    if g is not None:
        await emit(session, "access.grant.created", ("grant", g.id), grant_event(g),
                   building_id=g.building_id, person_id=g.person_id)
    return g is not None


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

    @bus.consumer("assets.asset.responsible_changed", name="responsible-changed")
    async def responsible_changed(session: AsyncSession, event: dict) -> None:
        """Whoever answers for an object has the role «responsible» on it; the one before loses it.
        A right on the same object given by hand is another grant and stays."""
        asset, data = UUID(event["data"]["asset_id"]), event["data"]
        gone = (await session.execute(delete(grants).where(
            grants.c.scope_kind == "asset", grants.c.scope_id == asset, grants.c.origin == "responsible")
            .returning(grants))).all()
        for g in gone:
            await emit(session, "access.grant.revoked", ("grant", g.id), grant_event(g),
                       building_id=g.building_id, person_id=g.person_id)
        if data["to"]:
            g = (await session.execute(pg_insert(grants).values(
                id=uuid7(), person_id=UUID(data["to"]), role="responsible", scope_kind="asset", scope_id=asset,
                building_id=UUID(event["building_id"]), origin="responsible", created_by="assets")
                .on_conflict_do_nothing(constraint="uq_grants_once").returning(grants))).one_or_none()
            if g is not None:
                await emit(session, "access.grant.created", ("grant", g.id), grant_event(g),
                           building_id=g.building_id, person_id=g.person_id)

    @bus.consumer("people.person.assigned", name="person-assigned")
    async def assigned(session: AsyncSession, event: dict) -> None:
        """Whoever works in a room sees it: «viewer» on the room, from the assignment."""
        d = event["data"]
        await give(session, UUID(d["person_id"]), "viewer", "room", UUID(d["room_id"]), UUID(d["building_id"]),
                   "assignment", "people")

    @bus.consumer("people.person.unassigned", name="person-unassigned")
    async def unassigned(session: AsyncSession, event: dict) -> None:
        """The assignment's grant goes with it; one given by hand on the same room stays."""
        d = event["data"]
        await revoke(session, grants.c.person_id == UUID(d["person_id"]), grants.c.scope_kind == "room",
                     grants.c.scope_id == UUID(d["room_id"]), grants.c.origin == "assignment")

    @bus.consumer("assets.asset.retired", name="asset-retired")
    async def asset_retired(session: AsyncSession, event: dict) -> None:
        await revoke(session, grants.c.scope_kind == "asset", grants.c.scope_id == UUID(event["data"]["asset_id"]))

    @bus.consumer("assets.asset.deleted", name="asset-deleted")
    async def asset_deleted(session: AsyncSession, event: dict) -> None:
        """An object taken off the scene for good: rights on it go with it."""
        await revoke(session, grants.c.scope_kind == "asset", grants.c.scope_id == UUID(event["data"]["asset_id"]))

    @bus.consumer("assets.asset.moved", name="asset-moved")
    async def asset_moved(session: AsyncSession, event: dict) -> None:
        """An object taken to another building: its grants are in that building now."""
        if event.get("building_id") and event["data"].get("from_building_id") != event["building_id"]:
            await session.execute(update(grants).where(
                grants.c.scope_kind == "asset", grants.c.scope_id == UUID(event["data"]["asset_id"]))
                .values(building_id=UUID(event["building_id"])))

    @bus.consumer("buildings.room.retired", name="room-retired")
    async def room_retired(session: AsyncSession, event: dict) -> None:
        await revoke(session, grants.c.scope_kind == "room", grants.c.scope_id == UUID(event["data"]["room_id"]))

    @bus.consumer("buildings.room.merged", name="room-merged")
    async def room_merged(session: AsyncSession, event: dict) -> None:
        """Rights on the merged rooms are rights on the heir; one already there is not given twice."""
        into = UUID(event["data"]["into"])
        rows = (await session.execute(select(grants).where(
            grants.c.scope_kind == "room", grants.c.scope_id.in_([UUID(x) for x in event["data"]["from"]])))).all()
        for g in rows:
            same = (await session.execute(select(grants.c.id).where(
                grants.c.person_id == g.person_id, grants.c.role == g.role, grants.c.scope_kind == "room",
                grants.c.scope_id == into, grants.c.origin == g.origin))).first()
            if same is None:
                await session.execute(update(grants).where(grants.c.id == g.id).values(scope_id=into))
            else:
                await revoke(session, grants.c.id == g.id)

    @bus.consumer("buildings.building.deleted", name="building-deleted")
    async def building_deleted(session: AsyncSession, event: dict) -> None:
        await revoke(session, grants.c.building_id == UUID(event["building_id"]))

    @bus.consumer("people.person.left", name="person-left")
    async def left(session: AsyncSession, event: dict) -> None:
        """Someone who left has no rights, whatever was given."""
        person = UUID(event["data"]["person_id"])
        gone = (await session.execute(delete(grants).where(grants.c.person_id == person).returning(grants))).all()
        await session.execute(delete(subjects).where(subjects.c.person_id == person))
        for g in gone:
            await emit(session, "access.grant.revoked", ("grant", g.id), grant_event(g),
                       building_id=g.building_id, person_id=g.person_id)
