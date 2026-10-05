"""What the requests and the handlers of the assets service share: the schema of a type,
values against it, rights over an object, the history."""
from __future__ import annotations

import re
import secrets
from datetime import date
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from twin_chassis import Identity, Problem, uuid7

from .models import asset_history, assets, type_schemas

STATE_NAMES = {"in_use": "в работе", "faulty": "неисправен", "in_repair": "в ремонте", "in_storage": "на складе",
               "retired": "списан"}
QR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"            # no look-alikes: read from a sticker


def qr_code() -> str:
    return "".join(secrets.choice(QR_ALPHABET) for _ in range(10))


def iso(t) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t else None


def asset_json(a) -> dict:
    return {
        "id": str(a.id), "type_id": str(a.type_id), "type_name": a.type_name,
        "category_id": str(a.category_id) if a.category_id else None, "schema_version": a.schema_version,
        "building_id": str(a.building_id), "floor_id": str(a.floor_id), "room_id": str(a.room_id),
        "x": a.x, "y": a.y, "angle": a.angle, "elevation": a.elevation,
        "container_id": str(a.container_id) if a.container_id else None,
        "inventory_no": a.inventory_no, "serial_no": a.serial_no, "state": a.state,
        "responsible_id": str(a.responsible_id) if a.responsible_id else None, "props": a.props, "note": a.note,
        "needs_placement": a.needs_placement, "needs_fill": a.needs_fill, "qr_code": a.qr_code,
        "version": a.version, "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
    }


def chain(a) -> list[tuple[str, object]]:
    """The object and everything above it, for a question about rights."""
    return [("asset", a.id), ("room", a.room_id), ("floor", a.floor_id), ("building", a.building_id)]


def scope_fields(a) -> dict:
    return {"building_id": a.building_id, "floor_id": a.floor_id, "room_id": a.room_id, "asset_id": a.id}


# ------------------------------------------------------------------- schemas ---
async def schema_of(request: Request, session, type_id: UUID, *, refresh: bool = False):
    """The type as the catalog last described it; asked of the catalog when not known yet."""
    row = None if refresh else (await session.execute(
        select(type_schemas).where(type_schemas.c.type_id == type_id))).one_or_none()
    if row is not None:
        return row
    token = request.headers.get("authorization", "").partition(" ")[2].strip() or None
    return await store_schema(session, await fetch_type(request.app.state.client, type_id, token))


async def fetch_type(client, type_id: UUID, token: str | None) -> dict:
    r = await client.get("catalog", f"/types/{type_id}", token=token)
    if r.status_code == 404:
        raise Problem(422, "invalid", "Нет такого типа в каталоге", errors=[{"field": "type_id", "message": "не найден"}])
    if r.status_code != 200:
        raise Problem(503, "service_unavailable", "Каталог не ответил", extra={"service": "catalog"})
    return r.json()


async def store_schema(session, t: dict):
    values = {"schema_version": t["schema_version"], "name": t["name"], "category_id": UUID(t["category_id"]),
              "container": t["container"], "portable": t["portable"], "archived": not t["active"],
              "schema": [p for p in t["schema"] if p["stored"] == "asset"], "updated_at": func.now()}
    return (await session.execute(pg_insert(type_schemas).values(type_id=UUID(t["id"]), **values)
                                  .on_conflict_do_update(index_elements=["type_id"], set_=values)
                                  .returning(type_schemas))).one()


def _fits(p: dict, value) -> bool:
    kind = p["kind"]
    if kind in ("text", "person"):
        return isinstance(value, str) and len(value) <= 2000
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "choice":
        return value in [o["value"] for o in (p.get("options") or [])]
    if kind == "date":
        try:
            return isinstance(value, str) and bool(date.fromisoformat(value))
        except ValueError:
            return False
    return False


def check_props(schema: list[dict], props: dict, *, changed: set[str] | None = None) -> None:
    """Values of the keys in `changed` (all, when None) must be properties of the schema and fit their kind;
    a required one cannot be emptied."""
    by_key = {p["key"]: p for p in schema}
    for key in (changed if changed is not None else props):
        p, value = by_key.get(key), props.get(key)
        if p is None:
            raise Problem(422, "invalid", f"У типа нет свойства «{key}»",
                          errors=[{"field": f"props.{key}", "message": "нет в схеме типа"}])
        if value is None or value == "":
            if p["required"]:
                raise Problem(422, "invalid", f"Свойство «{p['title']}» обязательно",
                              errors=[{"field": f"props.{key}", "message": "обязательное"}])
        elif not _fits(p, value):
            raise Problem(422, "invalid", f"Значение свойства «{p['title']}» не подходит",
                          errors=[{"field": f"props.{key}", "message": f"ожидается {p['kind']}"}])


def incomplete(schema: list[dict], props: dict) -> bool:
    """Whether the object's values do not pass the schema: a required one missing, one of the wrong kind."""
    for p in schema:
        value = props.get(p["key"])
        if value is None or value == "":
            if p["required"]:
                return True
        elif not _fits(p, value):
            return True
    return False


# -------------------------------------------------------------------- rights ---
async def actor(request: Request, me: Identity) -> dict:
    """Who is acting, for the history: the account and the person behind it."""
    person = None
    if me.kind == "user" and not me.is_admin:
        person = (await request.app.state.rights.scopes(request, me)).get("person_id")
    return {"actor_kind": me.kind, "actor_id": me.sub, "actor_person_id": UUID(person) if person else None}


async def record(session, asset_id: UUID, who: dict, action: str, changes: dict | None = None, *,
                 reverts: UUID | None = None, reason: str | None = None) -> None:
    await session.execute(insert(asset_history).values(
        id=uuid7(), asset_id=asset_id, action=action, changes=changes or {}, reverts=reverts, reason=reason, **who))


SYSTEM = {"actor_kind": "service", "actor_id": "assets", "actor_person_id": None}


def visible_filter(scopes: dict):
    """The condition picking the objects someone with these scopes may see; None — all of them."""
    if scopes.get("admin") or scopes.get("service"):
        return None
    ids: dict[str, list[UUID]] = {"building": [], "floor": [], "room": [], "asset": []}
    for g in scopes.get("grants") or []:
        ids[g["scope"]["kind"]].append(UUID(g["scope"]["id"]))
    nothing = [uuid7()]
    return (assets.c.building_id.in_(ids["building"] or nothing) | assets.c.floor_id.in_(ids["floor"] or nothing)
            | assets.c.room_id.in_(ids["room"] or nothing) | assets.c.id.in_(ids["asset"] or nothing))


def like(q: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", q.strip()) + "%"
