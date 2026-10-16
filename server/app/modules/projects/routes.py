import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.core.auth import CurrentActor
from app.core.db import DB
from app.modules.projects import api

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _file(data: bytes, name: str, media: str) -> Response:
    return Response(
        data,
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("")
def list_projects(
    actor: CurrentActor, session: DB, building_id: uuid.UUID | None = None, archived: bool = False
) -> dict[str, Any]:
    return {
        "items": [
            api.project_view(session, actor, p)
            for p in api.projects(session, actor, building_id, archived)
        ]
    }


class CreateIn(BaseModel):
    building_id: uuid.UUID
    name: str = Field(max_length=200)
    copy_of: uuid.UUID | None = None


@router.post("", status_code=201)
def create(body: CreateIn, actor: CurrentActor, session: DB) -> dict[str, Any]:
    p = api.create_project(session, actor, body.building_id, body.name, body.copy_of)
    return api.project_view(session, actor, p)


@router.get("/{project_id}")
def get(project_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return api.project_view(session, actor, api.get_project(session, actor, project_id))


class UpdateIn(BaseModel):
    version: int
    name: str | None = Field(default=None, max_length=200)
    archived: bool | None = None


@router.patch("/{project_id}")
def update(
    project_id: uuid.UUID, body: UpdateIn, actor: CurrentActor, session: DB
) -> dict[str, Any]:
    values = body.model_dump(exclude_none=True, exclude={"version"})
    p = api.update_project(session, actor, project_id, body.version, values)
    return api.project_view(session, actor, p)


@router.delete("/{project_id}", status_code=204)
def delete(project_id: uuid.UUID, actor: CurrentActor, session: DB) -> Response:
    api.delete_project(session, actor, project_id)
    return Response(status_code=204)


@router.get("/{project_id}/floors/{floor_id}")
def floor(
    project_id: uuid.UUID, floor_id: uuid.UUID, actor: CurrentActor, session: DB
) -> dict[str, Any]:
    """Расстановка этажа, как она будет по проекту."""
    p = api.get_project(session, actor, project_id)
    return api.floor_state(session, actor, p, floor_id)


class ChangesIn(BaseModel):
    create: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    update: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)
    delete: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


@router.post("/{project_id}/floors/{floor_id}/changes")
def changes(
    project_id: uuid.UUID, floor_id: uuid.UUID, body: ChangesIn, actor: CurrentActor, session: DB
) -> dict[str, Any]:
    return api.change_floor(
        session, actor, project_id, floor_id, body.create, body.update, body.delete
    )


@router.get("/{project_id}/specification")
def specification(project_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    spec = api.specification(session, actor, api.get_project(session, actor, project_id))
    return {"rows": spec["rows"], "total": float(spec["total"])}


@router.get("/{project_id}/compare")
def compare(
    project_id: uuid.UUID, actor: CurrentActor, session: DB, other: uuid.UUID | None = None
) -> dict[str, Any]:
    return api.compare(session, actor, project_id, other)


@router.get("/{project_id}/apply")
def apply_plan(project_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    return api.apply_plan(session, actor, project_id)


class ApplyIn(BaseModel):
    version: int
    # новый предмет → ключ выданной со склада единицы, «buy» (к закупке) или пусто
    choices: dict[str, str] = Field(default_factory=dict)


@router.post("/{project_id}/apply")
def apply(project_id: uuid.UUID, body: ApplyIn, actor: CurrentActor, session: DB) -> dict[str, Any]:
    result = api.apply_project(session, actor, project_id, body.version, body.choices)
    p = api.get_project(session, actor, project_id)
    return {**result, "project": api.project_view(session, actor, p)}


@router.get("/{project_id}/export.pdf")
def export_pdf(project_id: uuid.UUID, actor: CurrentActor, session: DB) -> Response:
    data, name = api.export_pdf(session, actor, project_id)
    return _file(data, name, "application/pdf")


@router.get("/{project_id}/export.xlsx")
def export_xlsx(project_id: uuid.UUID, actor: CurrentActor, session: DB) -> Response:
    data, name = api.export_xlsx(session, actor, project_id)
    return _file(data, name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
