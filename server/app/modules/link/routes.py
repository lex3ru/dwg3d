import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.auth import CurrentActor
from app.core.db import DB
from app.modules.link import api

router = APIRouter(prefix="/api/link", tags=["link"])


@router.get("/floors/{floor_id}")
def floor(floor_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    """Единицы этажа, «Неразмещённые» и сверка количественного учёта."""
    return api.floor_view(session, actor, floor_id)


@router.get("/units/{unit_id}")
def unit_item(unit_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return {"item": api.unit_item(session, actor, unit_id)}


class RegisterIn(BaseModel):
    floor_id: uuid.UUID
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    kind: str = "opening"
    date: dt.date | None = None
    supplier: str = Field(default="", max_length=300)
    basis: str = Field(default="", max_length=300)
    responsible: str = Field(default="", max_length=150)
    department: str = Field(default="", max_length=150)
    prices: dict[str, float] = Field(default_factory=dict)


@router.post("/register")
def register(body: RegisterIn, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return api.register(session, actor, api.Register(**body.model_dump()))


class RemoveIn(BaseModel):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    mode: str
    to_place: str | None = None
    reason: str = Field(default="", max_length=300)


@router.post("/remove")
def remove(body: RemoveIn, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return api.remove(session, actor, body.item_ids, body.mode, body.to_place, body.reason)
