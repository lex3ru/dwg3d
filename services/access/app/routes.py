"""Requests of the access service, under /api/access/v1 (contracts/openapi/access.v1.json)."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from twin_chassis import Identity, Problem, current_identity, emit, require_service, uuid7
from twin_chassis.access import NEEDS, decide, guest_scopes

from .models import grants, subjects

router = APIRouter()
Role = Literal["viewer", "responsible", "admin"]
ScopeKind = Literal["building", "floor", "room", "asset"]


def iso(t) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t else None


def grant_json(g) -> dict:
    return {"id": str(g.id), "person_id": str(g.person_id), "role": g.role,
            "scope": {"kind": g.scope_kind, "id": str(g.scope_id)}, "building_id": str(g.building_id),
            "origin": g.origin, "created_by": g.created_by,
            "created_at": g.created_at.isoformat().replace("+00:00", "Z")}


async def scopes_of_person(session, person_id: UUID | None) -> dict:
    rows = [] if person_id is None else (await session.execute(
        select(grants).where(grants.c.person_id == person_id).order_by(grants.c.created_at, grants.c.id))).all()
    items = [grant_json(g) for g in rows]
    return {"admin": False, "service": False, "person_id": str(person_id) if person_id else None, "grants": items,
            # a grant anywhere inside a building shows the plan of the building
            "buildings": sorted({g["building_id"] for g in items})}


async def scopes_of(session, me: Identity) -> dict:
    """What the caller may do where. The system administrator may everything; an account
    that is no person of the directory — nothing."""
    if me.kind == "guest":
        return guest_scopes(me)
    if me.is_admin or me.kind == "service":
        return {"admin": me.is_admin, "service": me.kind == "service", "person_id": None, "grants": [],
                "buildings": []}
    person_id = (await session.execute(select(subjects.c.person_id).where(subjects.c.user_sub == me.sub))).scalar()
    return await scopes_of_person(session, person_id)


@router.get("/me/scopes", tags=["scopes"], summary="Области доступа того, кто спрашивает")
async def my_scopes(request: Request, me: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        return await scopes_of(session, me)


@router.get("/scopes", tags=["scopes"], summary="Области доступа человека (служебный)")
async def person_scopes(person_id: UUID, request: Request, _: Identity = Depends(require_service)) -> dict:
    async with request.app.state.db.begin() as session:
        return await scopes_of_person(session, person_id)


class Area(BaseModel):
    kind: ScopeKind
    id: UUID


class Check(BaseModel):
    action: str = Field(description="view | plan | edit | move_portable | manage")
    chain: list[Area] = Field(min_length=1, max_length=8, description="Область и всё, что над ней")


class Checks(BaseModel):
    checks: list[Check] = Field(min_length=1, max_length=200)


@router.post("/check", tags=["scopes"], summary="Можно ли тому, кто спрашивает, выполнить действия над областями")
async def check(body: Checks, request: Request, me: Identity = Depends(current_identity)) -> dict:
    for c in body.checks:
        if c.action not in NEEDS:
            raise Problem(422, "invalid", f"Неизвестное действие «{c.action}»",
                          errors=[{"field": "checks.action", "message": "view, plan, edit, move_portable, manage"}])
    async with request.app.state.db.begin() as session:
        scopes = await scopes_of(session, me)
    return {"results": [{"allowed": decide(scopes, c.action, [(a.kind, a.id) for a in c.chain])} for c in body.checks]}


# ------------------------------------------------------------------- grants ---
class GrantIn(BaseModel):
    person_id: UUID
    role: Role
    scope: Area
    building_id: UUID = Field(description="Здание, внутри которого область")


async def _manages(session, me: Identity, building_id: UUID) -> None:
    """Grants of a building are given by its administrators (and the system administrator);
    to anyone else the building's grants do not exist."""
    scopes = await scopes_of(session, me)
    if decide(scopes, "manage", [("building", building_id)]):
        return
    if decide(scopes, "plan", [("building", building_id)]):
        raise Problem(403, "forbidden", "Права в здании выдаёт его администратор")
    raise Problem(404, "not_found", "Здание не найдено")


@router.get("/grants", tags=["grants"], summary="Назначения в здании")
async def list_grants(request: Request, building_id: UUID, person_id: UUID | None = None,
                      me: Identity = Depends(current_identity)) -> dict:
    async with request.app.state.db.begin() as session:
        await _manages(session, me, building_id)
        where = [grants.c.building_id == building_id]
        if person_id:
            where.append(grants.c.person_id == person_id)
        rows = (await session.execute(select(grants).where(*where).order_by(grants.c.created_at, grants.c.id))).all()
    return {"items": [grant_json(g) for g in rows]}


@router.post("/grants", status_code=201, tags=["grants"], summary="Выдать право")
async def create_grant(body: GrantIn, request: Request, me: Identity = Depends(current_identity)) -> dict:
    if body.scope.kind == "building" and body.scope.id != body.building_id:
        raise Problem(422, "invalid", "Область «здание» должна совпадать с building_id",
                      errors=[{"field": "scope.id", "message": "не то здание"}])
    async with request.app.state.db.begin() as session:
        await _manages(session, me, body.building_id)
        g = (await session.execute(pg_insert(grants).values(
            id=uuid7(), person_id=body.person_id, role=body.role, scope_kind=body.scope.kind, scope_id=body.scope.id,
            building_id=body.building_id, origin="manual", created_by=me.sub)
            .on_conflict_do_nothing(constraint="uq_grants_once").returning(grants))).one_or_none()
        if g is None:
            raise Problem(409, "exists", "Такое право уже выдано")
        await emit(session, "access.grant.created", ("grant", g.id), grant_event(g),
                   building_id=g.building_id, person_id=g.person_id)
    return grant_json(g)


@router.delete("/grants/{grant_id}", status_code=204, tags=["grants"], summary="Отозвать право")
async def revoke_grant(grant_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> None:
    async with request.app.state.db.begin() as session:
        g = (await session.execute(select(grants).where(grants.c.id == grant_id).with_for_update())).one_or_none()
        if g is None:
            raise Problem(404, "not_found", "Назначение не найдено")
        await _manages(session, me, g.building_id)
        await session.execute(delete(grants).where(grants.c.id == grant_id))
        await emit(session, "access.grant.revoked", ("grant", g.id), grant_event(g),
                   building_id=g.building_id, person_id=g.person_id)


def grant_event(g) -> dict:
    return {"grant_id": str(g.id), "person_id": str(g.person_id), "role": g.role,
            "scope": {"kind": g.scope_kind, "id": str(g.scope_id)}, "origin": g.origin}


@router.post("/reconcile", tags=["grants"], summary="Сверить автоматические назначения с привязками и ответственными")
async def reconcile_now(request: Request, me: Identity = Depends(current_identity)) -> dict:
    """Also happens by itself on start and every TWIN_RECONCILE_S seconds."""
    if not me.is_admin and me.kind != "service":
        raise Problem(403, "forbidden", "Сверку запускает администратор системы")
    return await request.app.state.reconcile()
