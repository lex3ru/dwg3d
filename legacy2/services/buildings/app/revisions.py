"""Revisions of a drawing (docs/CONTRACTS.md, section 3): a new build that would retire rooms or floors
waits as a draft. The administrator sees the differences, corrects which room of the build continues
which known one, and publishes — or discards, and the building stays as it was. Until then nothing
changes: the building, its objects, people and rights are the published ones.

Also the rooms by hand: merging rooms into one and splitting one by a line.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.ops import split as cut
from shapely.ops import unary_union
from sqlalchemy import func, insert, select, update
from twin_chassis import Identity, Problem, current_identity, emit, uuid7

from . import publish
from .models import drawings, floor_plans, revisions, rooms
from .rights import manages_building, manages_room
from .routes import iso, room_json

router = APIRouter()


def revision_json(r, explained: dict | None = None) -> dict:
    out = {"id": str(r.id), "building_id": str(r.building_id), "drawing_id": str(r.drawing_id),
           "build_id": str(r.build_id), "n": r.n, "status": r.status, "summary": r.summary,
           "decided_by": r.decided_by, "created_at": iso(r.created_at), "published_at": iso(r.published_at)}
    if explained is not None:
        out["differences"] = explained
        out["warnings"] = _warnings(r.result or {})
    return out


def _warnings(result: dict) -> list[str]:
    """What the build could not carry over: corrections of the 2D editor whose floor is gone, and the build's own."""
    out = [f"Правки 2D-редактора не перенесены: этаж «{u.get('_anchor', {}).get('name') or u.get('key')}» не найден"
           for u in result.get("edits_unmatched") or []]
    for w in result.get("warnings") or []:
        out.append(w if isinstance(w, str) else w.get("message") or str(w))
    return out


async def _revision(request: Request, me: Identity, revision_id: UUID, *, lock: bool = False):
    async with request.app.state.db.begin() as session:
        q = select(revisions).where(revisions.c.id == revision_id)
        r = (await session.execute(q)).one_or_none()
    if r is None:
        raise Problem(404, "not_found", "Ревизия не найдена")
    await request.app.state.rights.require(request, me, "manage", [("building", r.building_id)],
                                           what="Ревизия не найдена")
    return r


@router.get("/buildings/{building_id}/revisions", tags=["revisions"], summary="Ревизии чертежей здания")
async def list_revisions(building_id: UUID, request: Request, drawing_id: UUID | None = None,
                         _: Identity = Depends(manages_building)) -> dict:
    q = select(revisions).where(revisions.c.building_id == building_id)
    if drawing_id is not None:
        q = q.where(revisions.c.drawing_id == drawing_id)
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(q.order_by(revisions.c.created_at.desc()).limit(200))).all()
    return {"items": [revision_json(r) for r in rows]}


@router.get("/revisions/{revision_id}", tags=["revisions"],
            summary="Ревизия; у черновика — различия: какие помещения узнаны, новые, сняты, с другим контуром")
async def get_revision(revision_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    r = await _revision(request, me, revision_id)
    if r.status != "draft":
        return revision_json(r)
    async with request.app.state.db.begin() as session:
        d = (await session.execute(select(drawings).where(drawings.c.id == r.drawing_id))).one()
        return revision_json(r, await publish.explain(session, d, r.plans or {}, r.proposal))


class Match(BaseModel):
    candidate: str = Field(description="Этаж сборки")
    idx: int = Field(description="Номер помещения в плане этажа сборки")
    room_id: UUID | None = Field(description="Известное помещение, которое оно продолжает; null — новое")


class Matches(BaseModel):
    matches: list[Match] = Field(min_length=1, max_length=500)


@router.patch("/revisions/{revision_id}/matches", tags=["revisions"],
              summary="Поправить сопоставление: какое известное помещение продолжает помещение сборки")
async def patch_matches(revision_id: UUID, body: Matches, request: Request,
                        me: Identity = Depends(current_identity)) -> dict:
    await _revision(request, me, revision_id)
    async with request.app.state.db.begin() as session:
        r = (await session.execute(select(revisions).where(revisions.c.id == revision_id).with_for_update())).one()
        if r.status != "draft":
            raise Problem(409, "not_draft", "Ревизия уже опубликована или отброшена")
        d = (await session.execute(select(drawings).where(drawings.c.id == r.drawing_id))).one()
        proposal = {**r.proposal, "rooms": [dict(x) for x in r.proposal["rooms"]]}
        explained = await publish.explain(session, d, r.plans or {}, proposal)
        floor_of = {f["candidate"]: f["floor_id"] for f in proposal["floors"]}
        entries = {(x["candidate"], x["idx"]): x for x in proposal["rooms"]}
        for m in body.matches:
            entry = entries.get((m.candidate, m.idx))
            if entry is None:
                raise Problem(422, "invalid", "Нет такого помещения в сборке",
                              errors=[{"field": "matches", "message": f"{m.candidate}/{m.idx}"}])
            if m.room_id is not None:
                allowed = {c["id"] for c in explained["choices"].get(floor_of.get(m.candidate) or "", [])}
                if str(m.room_id) not in allowed:
                    raise Problem(422, "invalid", "Это помещение не с того же этажа",
                                  errors=[{"field": "matches", "message": str(m.room_id)}])
                for other in proposal["rooms"]:            # one known room continues one room of the build
                    if other is not entry and other["room_id"] == str(m.room_id):
                        other["room_id"], other["auto"] = None, False
            entry["room_id"], entry["auto"] = (str(m.room_id) if m.room_id else None), False
        explained = await publish.explain(session, d, r.plans or {}, proposal)
        r = (await session.execute(update(revisions).where(revisions.c.id == revision_id).values(
            proposal=proposal, summary=explained["count"]).returning(revisions))).one()
    return revision_json(r, explained)


@router.post("/revisions/{revision_id}/publish", tags=["revisions"],
             summary="Опубликовать черновик: сборка становится состоянием здания")
async def publish_revision(revision_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    await _revision(request, me, revision_id)
    async with request.app.state.db.begin() as session:
        r = (await session.execute(select(revisions).where(revisions.c.id == revision_id).with_for_update())).one()
        if r.status != "draft":
            raise Problem(409, "not_draft", "Ревизия уже опубликована или отброшена")
        d = (await session.execute(select(drawings).where(drawings.c.id == r.drawing_id).with_for_update())).one()
        if d.build_n >= r.n:
            raise Problem(409, "stale", "Чертёж уже опубликован в более новой сборке")
        summary = await publish.apply(session, d, {"id": str(r.build_id), "n": r.n}, r.result, r.plans or {},
                                      r.proposal, r.id)
        r = (await session.execute(update(revisions).where(revisions.c.id == revision_id).values(
            status="published", summary=summary, published_at=func.now(), decided_by=me.sub,
            result=None, plans=None).returning(revisions))).one()
    return revision_json(r)


@router.post("/revisions/{revision_id}/discard", tags=["revisions"],
             summary="Отбросить черновик: здание остаётся прежним")
async def discard_revision(revision_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    await _revision(request, me, revision_id)
    async with request.app.state.db.begin() as session:
        r = (await session.execute(select(revisions).where(revisions.c.id == revision_id).with_for_update())).one()
        if r.status != "draft":
            raise Problem(409, "not_draft", "Ревизия уже опубликована или отброшена")
        r = (await session.execute(update(revisions).where(revisions.c.id == revision_id).values(
            status="discarded", decided_by=me.sub, proposal=None, result=None, plans=None).returning(revisions))).one()
        await emit(session, "buildings.revision.discarded", ("revision", r.id),
                   {"revision_id": str(r.id), "drawing_id": str(r.drawing_id)}, building_id=r.building_id)
    return revision_json(r)


# ---------------------------------------------------------- rooms by hand ---
def _rings(geom) -> list:
    m = mapping(geom)
    return [[list(p) for p in ring] for ring in m["coordinates"]]


async def _plan_entry(session, room, values: dict | None) -> None:
    """Keep the plan of the floor in step with a room changed by hand: its outline (values) or gone (None)."""
    data = (await session.execute(select(floor_plans.c.data).where(floor_plans.c.floor_id == room.floor_id)
                                  .with_for_update())).scalar()
    if data is None or room.idx is None or room.idx >= len(data.get("rooms") or []):
        return
    entry = data["rooms"][room.idx]
    if values is None:
        entry.update(poly=[], area=0.0, merged=True)
    else:
        entry.update(values)
    await session.execute(update(floor_plans).where(floor_plans.c.floor_id == room.floor_id).values(data=data))


class Merge(BaseModel):
    with_: list[UUID] = Field(alias="with", min_length=1, max_length=20, description="Помещения, которые войдут в это")


@router.post("/rooms/{room_id}/merge", tags=["rooms"],
             summary="Объединить помещения: это — наследник; объекты, люди и права остальных переходят к нему")
async def merge_rooms(room_id: UUID, body: Merge, request: Request, _: Identity = Depends(manages_room)) -> dict:
    async with request.app.state.db.begin() as session:
        heir = (await session.execute(select(rooms).where(rooms.c.id == room_id).with_for_update())).one()
        others = (await session.execute(select(rooms).where(rooms.c.id.in_(body.with_)).with_for_update())).all()
        wrong = any(o.floor_id != heir.floor_id or o.status != "active" or o.id == heir.id for o in others)
        if len(others) != len(set(body.with_)) or wrong or heir.status != "active":
            raise Problem(422, "invalid", "Объединяются действующие помещения одного этажа",
                          errors=[{"field": "with", "message": "не тот этаж или снято"}])
        # the wall between them is part of the merged room: gaps up to 30 cm close
        union = unary_union([publish.polygon(r.polygon) for r in (heir, *others)]).buffer(0.15).buffer(-0.15)
        if not isinstance(union, Polygon):
            raise Problem(422, "invalid", "Помещения не соприкасаются — объединить их нельзя",
                          errors=[{"field": "with", "message": "не соседние"}])
        rings = _rings(union)
        area = round(sum(r.area for r in (heir, *others)), 2)
        await _plan_entry(session, heir, {"poly": rings, "area": area})
        for o in others:
            await _plan_entry(session, o, None)
        await session.execute(update(rooms).where(rooms.c.id.in_([o.id for o in others])).values(
            status="retired", retired_at=func.now(), merged_into=heir.id, idx=None, version=rooms.c.version + 1))
        heir = (await session.execute(update(rooms).where(rooms.c.id == heir.id).values(
            polygon=rings, area=area, version=rooms.c.version + 1).returning(rooms))).one()
        await emit(session, "buildings.room.merged", ("room", heir.id),
                   {"from": [str(o.id) for o in others], "into": str(heir.id), "floor_id": str(heir.floor_id)},
                   building_id=heir.building_id, floor_id=heir.floor_id, room_id=heir.id)
    return room_json(heir, outline=True)


class Split(BaseModel):
    line: list[tuple[float, float]] | None = Field(default=None, min_length=2, max_length=50,
                                                   description="Линия раздела в координатах плана этажа, м")
    parts: list[list[list[tuple[float, float]]]] | None = Field(default=None, min_length=2, max_length=20,
                                                                 description="Или сами части: контуры [кольца]")
    heir: int | None = Field(default=None, description="Какая часть сохраняет помещение; по умолчанию — большая")


@router.post("/rooms/{room_id}/split", tags=["rooms"],
             summary="Разделить помещение линией или на заданные части; объекты — по своим точкам")
async def split_room(room_id: UUID, body: Split, request: Request, _: Identity = Depends(manages_room)) -> dict:
    async with request.app.state.db.begin() as session:
        room = (await session.execute(select(rooms).where(rooms.c.id == room_id).with_for_update())).one()
        if room.status != "active":
            raise Problem(409, "retired", "Помещение снято")
        whole = publish.polygon(room.polygon)
        if body.line is not None:
            line = LineString(body.line)
            pieces = [g for g in cut(whole, line).geoms if isinstance(g, Polygon) and g.area > 0.05]
        elif body.parts is not None:
            pieces = [publish.polygon(p) for p in body.parts]
        else:
            raise Problem(422, "invalid", "Нужна линия раздела или части", errors=[{"field": "line", "message": "нет"}])
        if len(pieces) < 2 or any(p is None or isinstance(p, MultiPolygon) for p in pieces):
            raise Problem(422, "invalid", "Линия должна пересекать помещение от стены до стены",
                          errors=[{"field": "line", "message": "не делит помещение"}])
        heir_at = body.heir if body.heir is not None else max(range(len(pieces)), key=lambda i: pieces[i].area)
        if not 0 <= heir_at < len(pieces):
            raise Problem(422, "invalid", "Нет такой части", errors=[{"field": "heir", "message": "вне списка"}])
        data = (await session.execute(select(floor_plans.c.data).where(floor_plans.c.floor_id == room.floor_id)
                                      .with_for_update())).scalar()
        into = []
        for i, piece in enumerate(pieces):
            rings, area = _rings(piece), round(piece.area, 2)
            label = list(piece.representative_point().coords[0])
            if i == heir_at:
                if data is not None and room.idx is not None and room.idx < len(data.get("rooms") or []):
                    data["rooms"][room.idx].update(poly=rings, area=area, label=label)
                await session.execute(update(rooms).where(rooms.c.id == room.id).values(
                    polygon=rings, area=area, version=rooms.c.version + 1))
                continue
            idx = None
            if data is not None:
                data.setdefault("rooms", []).append({"name": room.name, "area": area, "poly": rings, "label": label})
                idx = len(data["rooms"]) - 1
            rid = uuid7()
            await session.execute(insert(rooms).values(
                id=rid, building_id=room.building_id, floor_id=room.floor_id, idx=idx, name=room.name,
                type=room.type, area=area, polygon=rings, manual=["name"] if "name" in room.manual else [],
                revision_id=room.revision_id))
            into.append(str(rid))
        if data is not None:
            await session.execute(update(floor_plans).where(floor_plans.c.floor_id == room.floor_id).values(data=data))
        await emit(session, "buildings.room.split", ("room", room.id),
                   {"from": str(room.id), "into": into, "heir": str(room.id), "floor_id": str(room.floor_id)},
                   building_id=room.building_id, floor_id=room.floor_id, room_id=room.id)
        rows = (await session.execute(select(rooms).where(rooms.c.id.in_([room.id, *map(UUID, into)])))).all()
    return {"heir": str(room.id), "rooms": [room_json(r, outline=True) for r in rows]}
