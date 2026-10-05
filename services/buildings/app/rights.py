"""Who may read and change what here (docs/CONTRACTS.md, section 2).

The plan of a building — its floors, rooms, model, pins — is open to anyone with
a grant anywhere inside it (`plan`); changes are for its administrators
(`manage`). To the rest the building does not exist: 404, not 403.
FastAPI dependencies: each finds the building of what the request is about.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from twin_chassis import Identity, Problem, current_identity

from .models import floors, pins, rooms


async def _check(request: Request, me: Identity, action: str, building_id: UUID | None, what: str) -> Identity:
    if building_id is None:
        raise Problem(404, "not_found", what)
    await request.app.state.rights.require(request, me, action, [("building", building_id)], what=what)
    return me


async def _building_of(request: Request, table, row_id: UUID) -> UUID | None:
    async with request.app.state.db.begin() as session:
        return (await session.execute(select(table.c.building_id).where(table.c.id == row_id))).scalar()


async def reads_building(building_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "plan", building_id, "Здание не найдено")


async def manages_building(building_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "manage", building_id, "Здание не найдено")


async def reads_floor(floor_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "plan", await _building_of(request, floors, floor_id), "Этаж не найден")


async def manages_floor(floor_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "manage", await _building_of(request, floors, floor_id), "Этаж не найден")


async def reads_room(room_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "plan", await _building_of(request, rooms, room_id), "Помещение не найдено")


async def manages_room(room_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "manage", await _building_of(request, rooms, room_id), "Помещение не найдено")


async def manages_pin(pin_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "manage", await _building_of(request, pins, pin_id), "Метка не найдена")
