"""Who may read and change what here: drawings and builds belong to a building.

Reading (the state of builds, their files — the model the viewer shows) is open
to anyone who may see the plan of the building; uploading, rebuilding, renaming,
deleting, exporting — to its administrators. To the rest: 404.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from twin_chassis import Identity, Problem, current_identity

from .models import builds, drawings


async def _check(request: Request, me: Identity, action: str, building_id: UUID | None, what: str) -> Identity:
    if building_id is None:
        raise Problem(404, "not_found", what)
    await request.app.state.rights.require(request, me, action, [("building", building_id)], what=what)
    return me


async def _of_drawing(request: Request, drawing_id: UUID) -> UUID | None:
    async with request.app.state.db.begin() as session:
        return (await session.execute(select(drawings.c.building_id).where(
            drawings.c.id == drawing_id, drawings.c.deleted_at.is_(None)))).scalar()


async def reads_building(building_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "plan", building_id, "Здание не найдено")


async def reads_drawing(drawing_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "plan", await _of_drawing(request, drawing_id), "Чертёж не найден")


async def manages_drawing(drawing_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    return await _check(request, me, "manage", await _of_drawing(request, drawing_id), "Чертёж не найден")


async def reads_build(build_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> Identity:
    async with request.app.state.db.begin() as session:
        building = (await session.execute(select(drawings.c.building_id).join(
            builds, builds.c.drawing_id == drawings.c.id).where(builds.c.id == build_id))).scalar()
    return await _check(request, me, "plan", building, "Сборка не найдена")
