"""Контракт отдельного счётчика проходов (ADR-0028, ТЗ 9.2)."""
import asyncio
import http.client
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, Header, Response
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import func, select, text

from app.core.auth import Admin, CurrentActor
from app.core.config import config
from app.core.db import DB
from app.core.errors import AppError, Forbidden, stale
from app.modules.journal import api as journal
from app.modules.surveillance import api
from app.modules.surveillance.models import CameraConnection, CountingConfig, Passage
from app.modules.surveillance.routes import PreviewResponse, router


class Point(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Settings(BaseModel):
    enabled: bool = False
    door: str = Field(default="Вход", min_length=1, max_length=100)
    p1: Point
    p2: Point
    inside: Point
    version: int = Field(ge=0)

    @model_validator(mode="after")
    def geometry(self):
        cross = ((self.p2.x-self.p1.x)*(self.inside.y-self.p1.y)
                 - (self.p2.y-self.p1.y)*(self.inside.x-self.p1.x))
        if abs(cross) < 0.001:
            raise ValueError("Укажите линию и точку со стороны входа вне линии.")
        return self


def service(authorization: Annotated[str | None, Header()] = None):
    token = config().analytics_token.get_secret_value()
    if not token or not secrets.compare_digest(
        (authorization or "").encode(), f"Bearer {token}".encode()
    ):
        raise Forbidden()


Service = Annotated[None, Depends(service)]


@router.get("/cameras/{item_id}/analytics")
def settings(item_id: uuid.UUID, actor: CurrentActor, session: DB):
    api.connection(session, actor, item_id)
    row = session.get(CountingConfig, item_id)
    return {"settings": row.settings if row else None, "version": row.version if row else 0,
            "state": (row.state if row and row.last_seen
                      and row.last_seen > datetime.now(UTC) - timedelta(seconds=60)
                      else "offline")}


@router.put("/cameras/{item_id}/analytics")
def configure(item_id: uuid.UUID, body: Settings, actor: Admin, session: DB):
    source = api.connection(session, actor, item_id)
    if source is None:
        raise AppError("Сначала настройте подключение камеры.")
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"counting:{item_id}"})
    row = session.get(CountingConfig, item_id)
    if body.version != (row.version if row else 0):
        raise stale("Настройки аналитики")
    if row is None:
        row = CountingConfig(item_id=item_id, version=0)
        session.add(row)
    row.settings = body.model_dump(exclude={"version"})
    row.version += 1
    row.last_seen = None
    row.state = None
    journal.record(session, actor, "surveillance.analytics", "Изменены настройки подсчёта",
                   entity=f"item:{item_id}", after={"version": row.version})
    session.flush()
    return {"settings": row.settings, "version": row.version}


@router.get("/service/config")
def configurations(response: Response, service: Service, session: DB):
    response.headers["Cache-Control"] = "no-store"
    rows = session.execute(select(CountingConfig, CameraConnection).join(
        CameraConnection, CountingConfig.item_id == CameraConnection.item_id))
    return {"cameras": [{"id": str(row.item_id), "version": row.version,
                         "connection_version": source.version, "source": api.stream_url(source),
                         **row.settings}
                        for row, source in rows if row.settings.get("enabled")]}


def _diagnostic_frame(path: str) -> bytes:
    settings = config()
    conn = http.client.HTTPConnection("127.0.0.1", settings.analytics_preview_port, timeout=2)
    try:
        token = settings.analytics_token.get_secret_value()
        conn.request("GET", path, headers={"Authorization": f"Bearer {token}"})
        result = conn.getresponse()
        if result.status == 200 and result.getheader("Content-Type") == "image/jpeg":
            frame = result.read(2 * 1024 * 1024)
            if frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9"):
                return frame
    except (OSError, http.client.HTTPException):
        pass
    finally:
        conn.close()
    raise AppError("Свежий кадр счётчика пока недоступен.", status=503)


@router.get("/cameras/{item_id}/analytics/frame")
def diagnostic_preview(item_id: uuid.UUID, actor: Admin, session: DB) -> PreviewResponse:
    source = api.connection(session, actor, item_id)
    row = session.get(CountingConfig, item_id)
    if not source or not row or not row.settings.get("enabled"):
        raise AppError("Включите подсчёт и сохраните разметку.", status=409)
    path = f"/{item_id}/{row.version}/{source.version}"

    async def frame():
        # Запрос к счётчику выполняется после закрытия транзакции (ADR-0027).
        yield await asyncio.to_thread(_diagnostic_frame, path)

    return PreviewResponse(frame(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class Event(BaseModel):
    id: uuid.UUID
    camera_id: uuid.UUID
    version: int = Field(ge=1)
    door: str = Field(min_length=1, max_length=100)
    direction: Literal["in", "out"]
    occurred_at: AwareDatetime


class Batch(BaseModel):
    events: list[Event] = Field(max_length=100)


@router.post("/service/events")
def ingest(body: Batch, service: Service, session: DB):
    accepted = []
    for event in sorted(body.events, key=lambda e: str(e.id)):
        if session.get(CameraConnection, event.camera_id) is None:
            # Удалённая камера не должна навсегда блокировать очередь сервиса.
            accepted.append(str(event.id))
            continue
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": f"passage:{event.id}"})
        if session.get(Passage, event.id) is None:
            session.add(Passage(**event.model_dump()))
            journal.record(session, None, "surveillance.passage", "Зарегистрирован проход",
                           entity=f"item:{event.camera_id}",
                           after={"event": str(event.id), "direction": event.direction})
        accepted.append(str(event.id))
    return {"accepted": accepted}


@router.get("/cameras/{item_id}/events")
def events(item_id: uuid.UUID, actor: CurrentActor, session: DB):
    api.connection(session, actor, item_id)
    rows = session.scalars(select(Passage).where(Passage.camera_id == item_id)
                           .order_by(Passage.occurred_at.desc()).limit(100))
    counts = dict(session.execute(select(Passage.direction, func.count()).where(
        Passage.camera_id == item_id).group_by(Passage.direction)).all())
    return {"counts": {"in": counts.get("in", 0), "out": counts.get("out", 0)},
            "items": [{"id": str(r.id), "door": r.door, "direction": r.direction,
                       "occurred_at": r.occurred_at, "received_at": r.received_at}
                      for r in rows]}


class Status(BaseModel):
    camera_id: uuid.UUID
    version: int
    state: Literal["running", "connecting", "error", "stopped"]


@router.post("/service/status")
def heartbeat(body: Status, service: Service, session: DB):
    row = session.get(CountingConfig, body.camera_id)
    if row and row.version == body.version:
        row.last_seen = datetime.now(UTC)
        row.state = body.state
        journal.record(session, None, "surveillance.status", "Состояние аналитики",
                       entity=f"item:{body.camera_id}", after={"state": body.state})
    return {"ok": True}
