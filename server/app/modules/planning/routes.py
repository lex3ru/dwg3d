import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.auth import AnyActor, CurrentActor
from app.core.db import DB
from app.modules.planning import api

router = APIRouter(prefix="/api", tags=["planning"])


@router.get("/floors/{floor_id}/items")
def floor_items(floor_id: uuid.UUID, actor: AnyActor, session: DB) -> dict[str, Any]:
    return {"items": [api.item_view(i) for i in api.floor_items(session, actor, floor_id)]}


@router.get("/items/{item_id}")
def get_item(item_id: uuid.UUID, actor: AnyActor, session: DB) -> dict[str, Any]:
    return api.item_view(api.get_item(session, actor, item_id))


class ChangesIn(BaseModel):
    # поля предметов — как в ответе GET; что не прислано, не меняется
    create: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    update: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    delete: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


@router.post("/floors/{floor_id}/items/changes")
def apply_changes(
    floor_id: uuid.UUID, body: ChangesIn, actor: CurrentActor, session: DB
) -> dict[str, Any]:
    return api.apply_changes(
        session, actor, floor_id, api.Changes(body.create, body.update, body.delete)
    )
