"""Comments to a point of a floor, a room or an object (docs/CONTRACTS.md, section 3).

A comment is seen by whoever sees its target: a point — by whoever sees the plan
of the building; a room or an object — by whoever has a right on it or above it.
The author and the building's administrators change and close it.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func, insert, select, update
from twin_chassis import Identity, Problem, current_identity, emit, forbid_guests, uuid7
from twin_chassis.access import decide

from .models import comments, floors, rooms
from .routes import iso

router = APIRouter()
Kind = Literal["point", "room", "asset"]


def comment_json(c) -> dict:
    return {"id": str(c.id), "building_id": str(c.building_id), "floor_id": str(c.floor_id) if c.floor_id else None,
            "room_id": str(c.room_id) if c.room_id else None, "target_kind": c.target_kind,
            "target_id": str(c.target_id) if c.target_id else None, "x": c.x, "y": c.y, "body": c.body,
            "author": {"sub": c.author_sub, "person_id": str(c.author_person_id) if c.author_person_id else None,
                       "name": c.author_name},
            "resolved_at": iso(c.resolved_at), "resolved_by": c.resolved_by, "created_at": iso(c.created_at),
            "updated_at": iso(c.updated_at), "version": c.version}


def _chain(c) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    if c.target_kind == "asset" and c.target_id:
        out.append(("asset", c.target_id))
    if c.room_id:
        out.append(("room", c.room_id))
    if c.floor_id:
        out.append(("floor", c.floor_id))
    out.append(("building", c.building_id))
    return out


def _sees(scopes: dict, c) -> bool:
    return decide(scopes, "plan" if c.target_kind == "point" else "view", _chain(c))


def _may_change(scopes: dict, me: Identity, c) -> bool:
    return c.author_sub == me.sub or decide(scopes, "manage", _chain(c))


async def _scopes(request: Request, me: Identity, *, reading: bool = True) -> dict:
    return await request.app.state.rights.scopes(request, me, reading=reading)


# a comment of spaces only says nothing
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class CommentIn(BaseModel):
    building_id: UUID
    target_kind: Kind
    target_id: UUID | None = Field(default=None, description="Помещение или объект")
    floor_id: UUID | None = Field(default=None, description="Для точки")
    x: float | None = None
    y: float | None = None
    body: Text


class CommentPatch(BaseModel):
    body: Text
    version: int


@router.get("/comments", tags=["comments"], summary="Комментарии к точке, помещению или объекту, видимые спрашивающему")
async def list_comments(request: Request, building_id: UUID, target_kind: Kind | None = None,
                        target_id: UUID | None = None, floor_id: UUID | None = None, resolved: bool = False,
                        me: Identity = Depends(current_identity)) -> dict:
    """Open ones by default; `resolved=true` — the closed ones too."""
    scopes = await _scopes(request, me)
    if not decide(scopes, "plan", [("building", building_id)]):
        raise Problem(404, "not_found", "Здание не найдено")
    if me.kind == "guest":                               # a guest by a link sees no comments
        return {"items": []}
    q = select(comments).where(comments.c.building_id == building_id).order_by(comments.c.created_at, comments.c.id)
    if target_kind is not None:
        q = q.where(comments.c.target_kind == target_kind)
    if target_id is not None:
        q = q.where(comments.c.target_id == target_id)
    if floor_id is not None:
        q = q.where(comments.c.floor_id == floor_id)
    if not resolved:
        q = q.where(comments.c.resolved_at.is_(None))
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(q)).all()
    return {"items": [comment_json(c) for c in rows if _sees(scopes, c)]}


async def _target(request: Request, session, me: Identity, scopes: dict, body: CommentIn) -> dict:
    """Where the target is (floor, room) — and that the author may see it."""
    where = {"floor_id": body.floor_id, "room_id": None, "x": None, "y": None}
    if body.target_kind == "point":
        if body.floor_id is None or body.x is None or body.y is None:
            raise Problem(422, "invalid", "Для точки нужны этаж и координаты",
                          errors=[{"field": "x", "message": "нет"}])
        f = (await session.execute(select(floors).where(floors.c.id == body.floor_id))).one_or_none()
        if f is None or f.building_id != body.building_id:
            raise Problem(422, "invalid", "Этаж не из этого здания", errors=[{"field": "floor_id", "message": "чужой"}])
        where.update(x=body.x, y=body.y)
    elif body.target_kind == "room":
        r = None
        if body.target_id:
            r = (await session.execute(select(rooms).where(rooms.c.id == body.target_id))).one_or_none()
        if r is None or r.building_id != body.building_id:
            raise Problem(422, "invalid", "Помещение не найдено", errors=[{"field": "target_id", "message": "нет"}])
        where.update(floor_id=r.floor_id, room_id=r.id)
    else:
        if body.target_id is None:
            raise Problem(422, "invalid", "Укажите объект", errors=[{"field": "target_id", "message": "нет"}])
        token = request.headers.get("authorization", "").partition(" ")[2].strip()
        r = await request.app.state.client.request("GET", "assets", f"/assets/{body.target_id}", token=token)
        if r.status_code == 404:
            raise Problem(404, "not_found", "Объект не найден")
        if r.status_code != 200:
            raise Problem(503, "service_unavailable", "Сервис объектов не ответил", extra={"service": "assets"})
        a = r.json()
        if a["building_id"] != str(body.building_id):
            raise Problem(422, "invalid", "Объект не из этого здания",
                          errors=[{"field": "target_id", "message": "чужой"}])
        where.update(floor_id=UUID(a["floor_id"]), room_id=UUID(a["room_id"]))
    return where


@router.post("/comments", status_code=201, tags=["comments"], summary="Оставить комментарий")
async def create_comment(body: CommentIn, request: Request, me: Identity = Depends(forbid_guests)) -> dict:
    scopes = await _scopes(request, me, reading=False)
    async with request.app.state.db.begin() as session:
        where = await _target(request, session, me, scopes, body)
        probe = SimpleNamespace(target_kind=body.target_kind, target_id=body.target_id,
                                building_id=body.building_id, **where)
        if not _sees(scopes, probe):
            raise Problem(404, "not_found", "Не найдено")
        person = scopes.get("person_id")
        c = (await session.execute(insert(comments).values(
            id=uuid7(), building_id=body.building_id, target_kind=body.target_kind, target_id=body.target_id,
            body=body.body.strip(), author_sub=me.sub, author_person_id=UUID(person) if person else None,
            author_name=me.name, **where).returning(comments))).one()
        await emit(session, "buildings.comment.created", ("comment", c.id),
                   {"comment_id": str(c.id), "target_kind": c.target_kind,
                    "target_id": str(c.target_id) if c.target_id else None, "author": c.author_name},
                   building_id=c.building_id, floor_id=c.floor_id, room_id=c.room_id)
    return comment_json(c)


async def _comment(session, comment_id: UUID, scopes: dict, *, lock: bool = False):
    q = select(comments).where(comments.c.id == comment_id)
    c = (await session.execute(q.with_for_update() if lock else q)).one_or_none()
    if c is None or not _sees(scopes, c):
        raise Problem(404, "not_found", "Комментарий не найден")
    return c


@router.patch("/comments/{comment_id}", tags=["comments"], summary="Изменить текст (автор или администратор)")
async def patch_comment(comment_id: UUID, body: CommentPatch, request: Request,
                        me: Identity = Depends(current_identity)) -> dict:
    scopes = await _scopes(request, me, reading=False)
    async with request.app.state.db.begin() as session:
        c = await _comment(session, comment_id, scopes, lock=True)
        if not _may_change(scopes, me, c):
            raise Problem(403, "forbidden", "Комментарий меняет его автор или администратор здания")
        if c.version != body.version:
            raise Problem(409, "version_conflict", "Комментарий изменил кто-то другой",
                          extra={"current": comment_json(c)})
        c = (await session.execute(update(comments).where(comments.c.id == comment_id).values(
            body=body.body.strip(), updated_at=func.now(), version=comments.c.version + 1).returning(comments))).one()
    return comment_json(c)


@router.post("/comments/{comment_id}/resolve", tags=["comments"],
             summary="Закрыть комментарий (автор или администратор)")
async def resolve_comment(comment_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> dict:
    scopes = await _scopes(request, me, reading=False)
    async with request.app.state.db.begin() as session:
        c = await _comment(session, comment_id, scopes, lock=True)
        if not _may_change(scopes, me, c):
            raise Problem(403, "forbidden", "Комментарий закрывает его автор или администратор здания")
        if c.resolved_at is None:
            c = (await session.execute(update(comments).where(comments.c.id == comment_id).values(
                resolved_at=datetime.now(UTC), resolved_by=me.sub, updated_at=func.now(),
                version=comments.c.version + 1).returning(comments))).one()
            await emit(session, "buildings.comment.resolved", ("comment", c.id),
                       {"comment_id": str(c.id), "target_kind": c.target_kind,
                        "target_id": str(c.target_id) if c.target_id else None, "author": c.author_name},
                       building_id=c.building_id, floor_id=c.floor_id, room_id=c.room_id)
    return comment_json(c)


@router.delete("/comments/{comment_id}", status_code=204, tags=["comments"],
               summary="Удалить комментарий (автор или администратор)")
async def delete_comment(comment_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> None:
    scopes = await _scopes(request, me, reading=False)
    async with request.app.state.db.begin() as session:
        c = await _comment(session, comment_id, scopes, lock=True)
        if not _may_change(scopes, me, c):
            raise Problem(403, "forbidden", "Комментарий удаляет его автор или администратор здания")
        await session.execute(delete(comments).where(comments.c.id == comment_id))
