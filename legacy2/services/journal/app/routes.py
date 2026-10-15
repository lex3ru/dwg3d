"""Requests of the journal, under /api/journal/v1 (contracts/openapi/journal.v1.json).

The feed of a building, a room, an object or a person: whoever has a right to
see the area of an event sees it; events about a person — the person themself
and the system administrator; the whole feed — the system administrator. A guest by a
link sees none of it (403 `guest`): the feed tells who did what.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from twin_chassis import Identity, Problem, current_identity, forbid_guests
from twin_chassis.access import decide

from .models import events

router = APIRouter(tags=["events"], dependencies=[Depends(forbid_guests)])


def event_json(e) -> dict:
    out = {"id": str(e.id), "type": e.type, "time": e.time.isoformat().replace("+00:00", "Z"),
           "actor": {"kind": e.actor_kind, "id": e.actor_id,
                     **({"person_id": str(e.actor_person_id)} if e.actor_person_id else {})},
           "subject": {"kind": e.subject_kind, "id": e.subject_id}, "data": e.data}
    for key in ("building_id", "floor_id", "room_id", "asset_id", "person_id"):
        value = getattr(e, key)
        if value is not None:
            out[key] = str(value)
    return out


def _sees(scopes: dict, e) -> bool:
    """The area of an event is in its envelope: the object, the room, the floor, the building — what is given."""
    if scopes.get("admin"):
        return True
    chain = [(kind, getattr(e, f"{kind}_id")) for kind in ("asset", "room", "floor", "building")
             if getattr(e, f"{kind}_id") is not None]
    if chain and decide(scopes, "view", chain):
        return True
    mine = scopes.get("person_id")
    return bool(mine) and (str(e.person_id) == mine or str(e.actor_person_id) == mine)


@router.get("/events", summary="Лента событий: здание, помещение, объект, человек; вид события и период")
async def list_events(request: Request, building_id: UUID | None = None, floor_id: UUID | None = None,
                      room_id: UUID | None = None, asset_id: UUID | None = None, person_id: UUID | None = None,
                      actor_id: str | None = None,
                      type: str | None = Query(default=None, description="Точно или по началу: «assets.»"),
                      from_: datetime | None = Query(default=None, alias="from"), to: datetime | None = None,
                      limit: int = 100, cursor: str | None = None,
                      me: Identity = Depends(current_identity)) -> dict:
    """Newest first. `cursor` — the `next` of the previous page. Without an area (a building, a room, an object)
    the feed is the system administrator's; a person's own events are open to them without an area."""
    scopes = await request.app.state.rights.scopes(request, me)
    area = any(x is not None for x in (building_id, floor_id, room_id, asset_id))
    if not area and not scopes.get("admin") and not (person_id and str(person_id) == scopes.get("person_id")):
        raise Problem(403, "forbidden", "Лента без выбора здания — администратору системы")
    q = select(events).order_by(events.c.time.desc(), events.c.id.desc())
    for column, value in ((events.c.building_id, building_id), (events.c.floor_id, floor_id),
                          (events.c.room_id, room_id), (events.c.asset_id, asset_id), (events.c.person_id, person_id)):
        if value is not None:
            q = q.where(column == value)
    if actor_id:
        q = q.where(events.c.actor_id == actor_id)
    if type:
        q = q.where(events.c.type.like(type + "%") if type.endswith(".") else events.c.type == type)
    if from_ is not None:
        q = q.where(events.c.time >= from_)
    if to is not None:
        q = q.where(events.c.time <= to)
    if cursor:
        try:
            time_, id_ = cursor.split("/", 1)
            q = q.where((events.c.time, events.c.id) < (datetime.fromisoformat(time_), UUID(id_)))
        except ValueError as ex:
            raise Problem(422, "invalid", "Неверный cursor",
                          errors=[{"field": "cursor", "message": "испорчен"}]) from ex
    limit = max(1, min(limit, 500))
    items: list[dict] = []
    last = None
    async with request.app.state.db.begin() as session:
        for page in range(0, 50):                        # pages of 200 until the feed is filled or the rows run out
            rows = (await session.execute(q.limit(200).offset(page * 200))).all()
            for e in rows:
                last = e
                if _sees(scopes, e):
                    items.append(event_json(e))
                    if len(items) == limit:
                        break
            if len(items) == limit or len(rows) < 200:
                break
    next_ = f"{last.time.isoformat()}/{last.id}" if last is not None and len(items) == limit else None
    return {"items": items, "next": next_}


@router.get("/events/{event_id}", summary="Событие")
async def get_event(event_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    scopes = await request.app.state.rights.scopes(request, me)
    async with request.app.state.db.begin() as session:
        e = (await session.execute(select(events).where(events.c.id == event_id))).one_or_none()
    if e is None or not _sees(scopes, e):
        raise Problem(404, "not_found", "Событие не найдено")
    return event_json(e)
