"""People in rooms (docs/CONTRACTS.md, section 7): who works where, at which workplace.

A person is seen — with contacts — by whoever sees a room they are assigned to;
assigning is for whoever manages the room. The room itself is the buildings
service's: it is asked where the room is (floor, building) and whether the
asker may see it at all. Who sits where is not for a guest by a link (403 `guest`).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from twin_chassis import Identity, Problem, current_identity, emit, forbid_guests, require_service
from twin_chassis.access import decide

from .models import assignments, persons
from .routes import _person, person_json

router = APIRouter(dependencies=[Depends(forbid_guests)])


def assignment_json(a) -> dict:
    return {"person_id": str(a.person_id), "room_id": str(a.room_id), "building_id": str(a.building_id),
            "floor_id": str(a.floor_id),
            "workplace_asset_id": str(a.workplace_asset_id) if a.workplace_asset_id else None,
            "created_at": a.created_at.isoformat().replace("+00:00", "Z")}


def chain(a) -> list[tuple[str, object]]:
    return [("room", a.room_id), ("floor", a.floor_id), ("building", a.building_id)]


def _token(request: Request) -> str:
    return request.headers.get("authorization", "").partition(" ")[2].strip()


async def _room(request: Request, room_id: UUID) -> dict:
    """The room as the buildings service shows it to the asker (404 to whoever may not see the plan)."""
    r = await request.app.state.client.request("GET", "buildings", f"/rooms/{room_id}", token=_token(request))
    if r.status_code == 404:
        raise Problem(404, "not_found", "Помещение не найдено")
    if r.status_code != 200:
        raise Problem(503, "service_unavailable", "Сервис зданий не ответил", extra={"service": "buildings"})
    return r.json()


def _chain_of(room: dict, room_id: UUID) -> list[tuple[str, object]]:
    return [("room", room_id), ("floor", UUID(room["floor_id"])), ("building", UUID(room["building_id"]))]


# ---------------------------------------------------------------- of a person ---
@router.get("/people/{person_id}/assignments", tags=["assignments"], summary="Помещения человека")
async def list_assignments(person_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    """All of them — to the system administrator and to the person themself; to others, administrators of
    buildings too, — in rooms they see: where someone sits in another building is not theirs to know."""
    scopes = await request.app.state.rights.scopes(request, me)
    everything = me.is_admin or me.kind == "service" or scopes.get("person_id") == str(person_id)
    async with request.app.state.db.begin() as session:
        await _person(session, person_id)
        rows = (await session.execute(select(assignments).where(assignments.c.person_id == person_id)
                                      .order_by(assignments.c.created_at))).all()
    return {"items": [assignment_json(a) for a in rows if everything or decide(scopes, "view", chain(a))]}


class AssignmentIn(BaseModel):
    workplace_asset_id: UUID | None = Field(default=None, description="Рабочее место: объект в этом помещении")


@router.put("/people/{person_id}/assignments/{room_id}", tags=["assignments"],
            summary="Привязать человека к помещению, необязательно — к рабочему месту в нём")
async def assign(person_id: UUID, room_id: UUID, body: AssignmentIn, request: Request,
                 me: Identity = Depends(current_identity)) -> dict:
    room = await _room(request, room_id)
    await request.app.state.rights.require(request, me, "manage", _chain_of(room, room_id), what="Помещение не найдено")
    where = {"building_id": UUID(room["building_id"]), "floor_id": UUID(room["floor_id"])}
    if body.workplace_asset_id is not None:
        r = await request.app.state.client.request("GET", "assets", f"/assets/{body.workplace_asset_id}",
                                                   token=_token(request))
        if r.status_code == 404 or (r.status_code == 200 and r.json().get("room_id") != str(room_id)):
            raise Problem(422, "invalid", "Рабочее место должно быть объектом этого помещения",
                          errors=[{"field": "workplace_asset_id", "message": "не в этом помещении"}])
        if r.status_code != 200:
            raise Problem(503, "service_unavailable", "Сервис объектов не ответил", extra={"service": "assets"})
    async with request.app.state.db.begin() as session:
        p = await _person(session, person_id)
        if p.status != "active":
            raise Problem(409, "left", "Человек выбыл")
        before = (await session.execute(select(assignments).where(
            assignments.c.person_id == person_id, assignments.c.room_id == room_id))).one_or_none()
        a = (await session.execute(pg_insert(assignments).values(
            person_id=person_id, room_id=room_id, workplace_asset_id=body.workplace_asset_id, created_by=me.sub,
            **where)
            .on_conflict_do_update(index_elements=["person_id", "room_id"],
                                   set_={"workplace_asset_id": body.workplace_asset_id, **where})
            .returning(assignments))).one()
        if before is None or before.workplace_asset_id != a.workplace_asset_id:
            await emit(session, "people.person.assigned", ("person", person_id),
                       {"person_id": str(person_id), "building_id": str(a.building_id), "floor_id": str(a.floor_id),
                        "room_id": str(room_id),
                        "workplace_asset_id": str(a.workplace_asset_id) if a.workplace_asset_id else None},
                       building_id=a.building_id, floor_id=a.floor_id, room_id=room_id, person_id=person_id)
    return assignment_json(a)


@router.delete("/people/{person_id}/assignments/{room_id}", status_code=204, tags=["assignments"],
               summary="Отвязать человека от помещения")
async def unassign(person_id: UUID, room_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> None:
    async with request.app.state.db.begin() as session:
        a = (await session.execute(select(assignments).where(
            assignments.c.person_id == person_id, assignments.c.room_id == room_id))).one_or_none()
        if a is None:
            raise Problem(404, "not_found", "Привязки нет")
        await request.app.state.rights.require(request, me, "manage", chain(a), what="Помещение не найдено")
        await session.execute(delete(assignments).where(
            assignments.c.person_id == person_id, assignments.c.room_id == room_id))
        await emit(session, "people.person.unassigned", ("person", person_id),
                   {"person_id": str(person_id), "building_id": str(a.building_id), "floor_id": str(a.floor_id),
                    "room_id": str(room_id)},
                   building_id=a.building_id, floor_id=a.floor_id, room_id=room_id, person_id=person_id)


# ------------------------------------------------------------------ of a room ---
@router.get("/rooms/{room_id}/people", tags=["assignments"], summary="Люди помещения, с контактами")
async def room_people(room_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    room = await _room(request, room_id)
    await request.app.state.rights.require(request, me, "view", _chain_of(room, room_id), what="Помещение не найдено")
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(persons, assignments.c.workplace_asset_id)
                                      .join(assignments, assignments.c.person_id == persons.c.id)
                                      .where(assignments.c.room_id == room_id, persons.c.status == "active")
                                      .order_by(persons.c.full_name, persons.c.id))).all()
    items = [{**person_json(p), "workplace_asset_id": str(p.workplace_asset_id) if p.workplace_asset_id else None}
             for p in rows]
    return {"items": items}


@router.get("/assignments", tags=["assignments"], summary="Все привязки (служебный: для сверки прав)")
async def all_assignments(request: Request, _: Identity = Depends(require_service)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(assignments).order_by(assignments.c.created_at))).all()
    return {"items": [assignment_json(a) for a in rows]}
