"""Подключение камеры: права здания, журнал и секреты (ТЗ 8.4, 9.2; ADR-0027)."""

import uuid
from urllib.parse import quote, urlsplit, urlunsplit

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Forbidden, stale
from app.modules.building import api as building
from app.modules.catalog import api as catalog
from app.modules.journal import api as journal
from app.modules.planning import api as planning
from app.modules.surveillance.models import CameraConnection
from app.modules.surveillance.secrets import decrypt, encrypt


def validate_address(address: str) -> str:
    address = address.strip()
    try:
        parsed = urlsplit(address)
        valid = (parsed.scheme == "rtsp" and bool(parsed.hostname)
                 and parsed.port != 0 and parsed.username is None and not parsed.fragment
                 and not any(c.isspace() or ord(c) < 32 for c in address))
    except ValueError:
        valid = False
    if not valid:
        raise AppError("Укажите адрес rtsp://адрес-камеры:554/поток. "
                       "Логин и пароль вводятся отдельно.", field="address")
    return address


def connection(session: Session, actor: Actor, item_id: uuid.UUID) -> CameraConnection | None:
    if actor.is_guest:
        raise Forbidden()
    planning.get_item(session, actor, item_id)
    return session.get(CameraConnection, item_id)


def view(source: CameraConnection | None, actor: Actor) -> dict:
    out = {"configured": source is not None, "version": source.version if source else 0,
           "analytics_available": False}
    if actor.is_admin:
        out.update(address=source.address if source else "",
                   username=source.username if source else "",
                   has_password=bool(source and source.password))
    return out


def save(session: Session, actor: Actor, item_id: uuid.UUID, *, address: str,
         username: str, password: str | None, version: int) -> dict:
    if not actor.is_admin:
        raise Forbidden()
    item = planning.get_item(session, actor, item_id)
    address = validate_address(address)
    # В том числе первый INSERT: два администратора не перезаписывают изменения друг друга.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"surveillance:{item_id}"})
    source = session.get(CameraConnection, item_id)
    if version != (source.version if source else 0):
        raise stale("Подключение камеры")
    if source is None:
        source = CameraConnection(item_id=item_id, version=0, password=b"")
        session.add(source)
    source.address = address
    source.username = username
    if password is not None:
        source.password = encrypt(password)
    source.version += 1
    journal.record(session, actor, "surveillance.configure", "Изменено подключение камеры",
                   entity=f"item:{item_id}",
                   refs=[f"building:{item.building_id}", f"floor:{item.floor_id}"],
                   after={"configured": True, "version": source.version})
    session.flush()
    return view(source, actor)


def stream_url(source: CameraConnection) -> str:
    parsed = urlsplit(source.address)
    credentials = ""
    if source.username:
        user = quote(source.username, safe="")
        password = quote(decrypt(source.password), safe="")
        credentials = f"{user}:{password}@"
    return urlunsplit(parsed._replace(netloc=credentials + parsed.netloc))


def cameras(session: Session, actor: Actor, building_id: uuid.UUID) -> list[dict]:
    """Все камеры здания, включая ещё не подключённые (ТЗ 8.4, ADR-0027)."""
    if actor.is_guest:
        raise Forbidden()
    building.get_building(session, actor, building_id)
    types = {t.id: t for t in catalog.types_with(
        session, ["Разрешение по горизонтали", "Угол обзора по горизонтали, макс."]
    )}
    out = []
    for floor in building.floors(session, building_id):
        items = planning.floor_items(session, actor, floor.id)
        ids = [item.id for item in items]
        connected = set(session.scalars(select(CameraConnection.item_id).where(
            CameraConnection.item_id.in_(ids)
        ))) if ids else set()
        rooms = {r.id: " ".join(filter(None, [r.number, r.name]))
                 for r in building.live_rooms(session, floor.id)}
        for item in items:
            if item.type_id not in types and item.id not in connected:
                continue
            kind = types.get(item.type_id)
            title = item.label or (kind.name if kind else "Камера")
            out.append({"id": str(item.id), "title": title,
                        "type_name": kind.name if kind else "Камера", "floor_id": str(floor.id),
                        "floor_name": floor.name, "room": rooms.get(item.room_id, "Вне помещения"),
                        "configured": item.id in connected})
    return out
