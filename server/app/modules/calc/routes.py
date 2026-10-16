import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.auth import CurrentActor
from app.core.db import DB
from app.modules.calc import api

router = APIRouter(prefix="/api/calc", tags=["calc"])


@router.get("")
def calculations(actor: CurrentActor, session: DB) -> dict[str, Any]:
    """Расчёты для списка в редакторе: что нужно, параметры, у каких типов."""
    return {"items": api.calculations(session)}


class RunIn(BaseModel):
    # расстановка как на экране (и пока предмет тащат); нет — сохранённая
    items: list[dict[str, Any]] | None = Field(default=None, max_length=5000)
    options: dict[str, str] = Field(default_factory=dict)


@router.post("/{key}/floors/{floor_id}")
def run(
    key: str, floor_id: uuid.UUID, body: RunIn, actor: CurrentActor, session: DB
) -> dict[str, Any]:
    return api.run(session, actor, key, floor_id, body.items, body.options)
