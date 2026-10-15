"""Links for looking without an account (docs/TZ.md, 4.6): the administrator of a building gives a link to
the building, a floor or a room, until a date. Whoever opens it gets a guest token for ten minutes, renewed
by the gateway while the link is good; a revoked or expired link opens nothing, and a session made with it
ends at the next renewal. Every opening is an event, so the journal shows who looked and when.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update
from twin_chassis import Identity, Problem, current_identity, emit, uuid7
from twin_chassis.auth import GUEST_ISSUER

from .models import shares, signing_keys
from .routes import iso

router = APIRouter(tags=["shares"])
TOKEN_S = 600


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def signing_key(db) -> tuple[str, rsa.RSAPrivateKey]:
    """The key guest tokens are signed with: made once, kept in the service's database."""
    async with db.begin() as session:
        row = (await session.execute(select(signing_keys).order_by(signing_keys.c.created_at.desc()))).first()
        if row is None:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
            kid = f"guest-{secrets.token_hex(4)}"
            await session.execute(insert(signing_keys).values(kid=kid, private_pem=pem))
            return kid, key
    return row.kid, serialization.load_pem_private_key(row.private_pem.encode(), password=None)


def share_json(s, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    state = "revoked" if s.revoked_at else "expired" if s.expires_at <= now else "active"
    return {"id": str(s.id), "building_id": str(s.building_id), "scope": {"kind": s.scope_kind, "id": str(s.scope_id)},
            "floor_id": str(s.floor_id) if s.floor_id else None, "note": s.note, "expires_at": iso(s.expires_at),
            "revoked_at": iso(s.revoked_at), "state": state, "opened": s.opened,
            "last_opened_at": iso(s.last_opened_at), "created_by": s.created_by, "created_at": iso(s.created_at)}


async def _manages(request: Request, me: Identity, building_id: UUID) -> None:
    from .routes import _manages as manages
    async with request.app.state.db.begin() as session:
        await manages(session, me, building_id)


class ShareIn(BaseModel):
    building_id: UUID
    scope: dict = Field(description="{kind: building | floor | room, id}")
    floor_id: UUID | None = Field(default=None, description="Для помещения — его этаж (план этого этажа увидит гость)")
    expires_at: datetime = Field(description="До какого времени ссылка открывается")
    note: str = Field(default="", max_length=200, description="Кому и зачем")


@router.get("/shares", summary="Ссылки для просмотра без учётной записи")
async def list_shares(request: Request, building_id: UUID, me: Identity = Depends(current_identity)) -> dict:
    await _manages(request, me, building_id)
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(shares).where(shares.c.building_id == building_id)
                                      .order_by(shares.c.created_at.desc()))).all()
    return {"items": [share_json(s) for s in rows]}


@router.post("/shares", status_code=201, summary="Выдать ссылку: на здание, этаж или помещение, до даты")
async def create_share(body: ShareIn, request: Request, me: Identity = Depends(current_identity)) -> dict:
    """The answer holds the link once: it is not kept anywhere and cannot be shown again."""
    kind: Literal["building", "floor", "room"] | str = body.scope.get("kind", "")
    try:
        scope_id = UUID(str(body.scope.get("id")))
    except ValueError as ex:
        raise Problem(422, "invalid", "Нет области", errors=[{"field": "scope.id", "message": "не uuid"}]) from ex
    if kind not in ("building", "floor", "room"):
        raise Problem(422, "invalid", "Ссылка — на здание, этаж или помещение",
                      errors=[{"field": "scope.kind", "message": "building, floor или room"}])
    if kind == "building" and scope_id != body.building_id:
        raise Problem(422, "invalid", "Область «здание» должна совпадать с building_id",
                      errors=[{"field": "scope.id", "message": "не то здание"}])
    floor = scope_id if kind == "floor" else body.floor_id
    if kind == "room" and floor is None:
        raise Problem(422, "invalid", "Для помещения нужен его этаж", errors=[{"field": "floor_id", "message": "нет"}])
    if body.expires_at.tzinfo is None or body.expires_at <= datetime.now(UTC):
        raise Problem(422, "invalid", "Срок ссылки — в будущем, с часовым поясом",
                      errors=[{"field": "expires_at", "message": "в прошлом"}])
    await _manages(request, me, body.building_id)
    token = secrets.token_urlsafe(24)
    async with request.app.state.db.begin() as session:
        s = (await session.execute(insert(shares).values(
            id=uuid7(), token_hash=_hash(token), building_id=body.building_id, scope_kind=kind, scope_id=scope_id,
            floor_id=floor, note=body.note.strip(), expires_at=body.expires_at, created_by=me.sub)
            .returning(shares))).one()
        await emit(session, "access.share.created", ("share", s.id),
                   {"share_id": str(s.id), "scope": {"kind": kind, "id": str(scope_id)},
                    "expires_at": iso(s.expires_at)},
                   building_id=s.building_id, **({"floor_id": floor} if floor else {}))
    url = f"{request.app.state.settings.public_url}/s/{token}"
    return {**share_json(s), "token": token, "url": url}


@router.delete("/shares/{share_id}", status_code=204, summary="Отозвать ссылку")
async def revoke_share(share_id: UUID, request: Request, me: Identity = Depends(current_identity)) -> None:
    async with request.app.state.db.begin() as session:
        s = (await session.execute(select(shares).where(shares.c.id == share_id))).one_or_none()
    if s is None:
        raise Problem(404, "not_found", "Ссылка не найдена")
    await _manages(request, me, s.building_id)
    async with request.app.state.db.begin() as session:
        if s.revoked_at is None:
            await session.execute(update(shares).where(shares.c.id == share_id).values(revoked_at=datetime.now(UTC)))
            await emit(session, "access.share.revoked", ("share", s.id),
                       {"share_id": str(s.id), "scope": {"kind": s.scope_kind, "id": str(s.scope_id)}},
                       building_id=s.building_id)


class Open(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    renew: bool = Field(default=False, description="Продление уже открытого просмотра, а не новое открытие")
    address: str | None = Field(default=None, max_length=100, description="Откуда открыли (передаёт шлюз)")


@router.post("/shares/open", summary="Открыть ссылку: гостевой токен на её область")
async def open_share(body: Open, request: Request) -> dict:
    """No sign-in needed: the link itself is the proof. A link unknown, revoked or expired — 404, all alike."""
    now = datetime.now(UTC)
    async with request.app.state.db.begin() as session:
        s = (await session.execute(select(shares).where(shares.c.token_hash == _hash(body.token))
                                   .with_for_update())).one_or_none()
        if s is None or s.revoked_at is not None or s.expires_at <= now:
            raise Problem(404, "not_found", "Ссылка недействительна: отозвана, просрочена или неверна")
        if not body.renew:
            await session.execute(update(shares).where(shares.c.id == s.id).values(
                opened=shares.c.opened + 1, last_opened_at=now))
            await emit(session, "access.share.opened", ("share", s.id),
                       {"share_id": str(s.id), "scope": {"kind": s.scope_kind, "id": str(s.scope_id)},
                        "address": body.address, "note": s.note},
                       building_id=s.building_id, **({"floor_id": s.floor_id} if s.floor_id else {}))
    kid, key = request.app.state.signing
    exp = int(min(time.time() + TOKEN_S, s.expires_at.timestamp()))
    claims = {"iss": GUEST_ISSUER, "sub": f"guest:{s.id}", "iat": int(time.time()), "exp": exp,
              "area": {"kind": s.scope_kind, "id": str(s.scope_id)}, "building_id": str(s.building_id),
              "floor_id": str(s.floor_id) if s.floor_id else None}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})
    return {"token": token, "expires_in": exp - int(time.time()), "building_id": str(s.building_id),
            "scope": {"kind": s.scope_kind, "id": str(s.scope_id)}, "floor_id": claims["floor_id"],
            "expires_at": iso(s.expires_at)}


@router.get("/.well-known/jwks.json", summary="Ключи, которыми подписаны гостевые токены")
async def jwks(request: Request) -> dict:
    kid, key = request.app.state.signing
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}
