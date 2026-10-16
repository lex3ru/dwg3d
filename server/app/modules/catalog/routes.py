import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Response, UploadFile
from pydantic import BaseModel, Field

from app.core.auth import Admin, AnyActor
from app.core.db import DB
from app.modules.catalog import api, excel, model3d

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("")
def tree(actor: AnyActor, session: DB, archived: bool = False) -> dict[str, Any]:
    return api.tree(session, actor, archived)


# ---------------------------------------------------------------- слои


class LayerIn(BaseModel):
    version: int | None = None
    name: str | None = Field(default=None, max_length=100)
    color: str | None = None
    icon: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=300)
    position: int | None = None
    visible: bool | None = None


@router.post("/layers", status_code=201)
def create_layer(body: LayerIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.layer_view(api.create_layer(session, actor, body.model_dump(exclude_none=True)))


@router.patch("/layers/{layer_id}")
def update_layer(layer_id: uuid.UUID, body: LayerIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.layer_view(
        api.update_layer(session, actor, layer_id, body.model_dump(exclude_none=True))
    )


@router.delete("/layers/{layer_id}", status_code=204)
def delete_layer(layer_id: uuid.UUID, actor: Admin, session: DB) -> None:
    api.delete_layer(session, actor, layer_id)


# ---------------------------------------------------------------- наборы и характеристики


class SetIn(BaseModel):
    name: str = Field(max_length=100)
    version: int | None = None


@router.post("/sets", status_code=201)
def create_set(body: SetIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.set_view(api.create_set(session, actor, body.name))


@router.patch("/sets/{set_id}")
def update_set(set_id: uuid.UUID, body: SetIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.set_view(api.update_set(session, actor, set_id, body.name, body.version or 0))


@router.delete("/sets/{set_id}", status_code=204)
def delete_set(set_id: uuid.UUID, actor: Admin, session: DB) -> None:
    api.delete_set(session, actor, set_id)


class CharIn(BaseModel):
    version: int | None = None
    set_id: uuid.UUID | None = None
    type_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=150)
    kind: str | None = None
    unit: str | None = Field(default=None, max_length=20)
    choices: list[str] | None = None
    level: str | None = None
    required: bool | None = None
    note: str | None = Field(default=None, max_length=300)
    position: int | None = None


@router.post("/characteristics", status_code=201)
def create_characteristic(body: CharIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.char_view(
        api.create_characteristic(session, actor, body.model_dump(exclude_none=True))
    )


@router.patch("/characteristics/{char_id}")
def update_characteristic(
    char_id: uuid.UUID, body: CharIn, actor: Admin, session: DB
) -> dict[str, Any]:
    values = body.model_dump(exclude_none=True)
    values.pop("set_id", None)
    values.pop("type_id", None)
    return api.char_view(api.update_characteristic(session, actor, char_id, values))


@router.delete("/characteristics/{char_id}", status_code=204)
def delete_characteristic(char_id: uuid.UUID, actor: Admin, session: DB) -> None:
    api.delete_characteristic(session, actor, char_id)


# ---------------------------------------------------------------- типы


class TypeIn(BaseModel):
    model_config = {"extra": "forbid"}
    version: int | None = None
    name: str | None = Field(default=None, max_length=200)
    layer_id: uuid.UUID | None = None
    set_ids: list[uuid.UUID] | None = None
    width: float | None = None
    depth: float | None = None
    height: float | None = None
    mount: str | None = None
    mount_height: float | None = None
    top_view: str | None = None
    icon: str | None = Field(default=None, max_length=40)
    price: float | None = None
    accounting: str | None = None
    unit: str | None = Field(default=None, max_length=20)
    life_months: int | None = None
    container: bool | None = None
    model_transform: dict[str, float | bool] | None = None


def _type_values(body: TypeIn) -> dict[str, Any]:
    # явно присланное null — «очистить» (слой, размеры, цена); не присланное — не трогать
    return body.model_dump(exclude_unset=True)


@router.get("/types/{type_id}")
def get_type(type_id: uuid.UUID, actor: AnyActor, session: DB) -> dict[str, Any]:
    return api.type_view(session, api.get_type(session, type_id), actor)


@router.post("/types", status_code=201)
def create_type(body: TypeIn, actor: Admin, session: DB) -> dict[str, Any]:
    t = api.create_type(session, actor, _type_values(body))
    return api.type_view(session, t, actor)


@router.patch("/types/{type_id}")
def update_type(type_id: uuid.UUID, body: TypeIn, actor: Admin, session: DB) -> dict[str, Any]:
    t = api.update_type(session, actor, type_id, _type_values(body))
    return api.type_view(session, t, actor)


@router.post("/types/{type_id}/archive")
def archive_type(type_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return api.type_view(session, api.set_archived_type(session, actor, type_id, True), actor)


@router.post("/types/{type_id}/unarchive")
def unarchive_type(type_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return api.type_view(session, api.set_archived_type(session, actor, type_id, False), actor)


@router.delete("/types/{type_id}", status_code=204)
def delete_type(type_id: uuid.UUID, actor: Admin, session: DB) -> None:
    api.delete_type(session, actor, type_id)


class ValuesIn(BaseModel):
    values: dict[str, Any]


@router.put("/types/{type_id}/values")
def type_values(type_id: uuid.UUID, body: ValuesIn, actor: Admin, session: DB) -> dict[str, Any]:
    t = api.get_type(session, type_id)
    api.set_values(session, actor, body.values, item_type=t)
    return api.type_view(session, t, actor)


@router.post("/types/{type_id}/model3d")
def upload_model3d(
    type_id: uuid.UUID, file: UploadFile, actor: Admin, session: DB
) -> dict[str, Any]:
    t = model3d.attach(session, actor, type_id, file.file, file.filename or "модель.glb")
    return api.type_view(session, t, actor)


@router.delete("/types/{type_id}/model3d")
def remove_model3d(type_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    t = api.attach_model3d(session, actor, type_id, None, None)
    return api.type_view(session, t, actor)


# ---------------------------------------------------------------- модели


class ModelIn(BaseModel):
    version: int | None = None
    manufacturer: str | None = Field(default=None, max_length=150)
    name: str | None = Field(default=None, max_length=200)
    article: str | None = Field(default=None, max_length=100)
    supplier: str | None = Field(default=None, max_length=200)
    price: float | None = None


@router.post("/types/{type_id}/models", status_code=201)
def create_model(type_id: uuid.UUID, body: ModelIn, actor: Admin, session: DB) -> dict[str, Any]:
    api.create_model(session, actor, type_id, body.model_dump(exclude_unset=True))
    return api.type_view(session, api.get_type(session, type_id), actor)


@router.patch("/models/{model_id}")
def update_model(model_id: uuid.UUID, body: ModelIn, actor: Admin, session: DB) -> dict[str, Any]:
    m = api.update_model(session, actor, model_id, body.model_dump(exclude_unset=True))
    return api.type_view(session, api.get_type(session, m.type_id), actor)


@router.put("/models/{model_id}/values")
def model_values(model_id: uuid.UUID, body: ValuesIn, actor: Admin, session: DB) -> dict[str, Any]:
    m = api.get_model(session, model_id)
    t = api.get_type(session, m.type_id)
    api.set_values(session, actor, body.values, item_type=t, model=m)
    return api.type_view(session, t, actor)


@router.post("/models/{model_id}/archive")
def archive_model(model_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    m = api.set_archived_model(session, actor, model_id, True)
    return api.type_view(session, api.get_type(session, m.type_id), actor)


@router.post("/models/{model_id}/unarchive")
def unarchive_model(model_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    m = api.set_archived_model(session, actor, model_id, False)
    return api.type_view(session, api.get_type(session, m.type_id), actor)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: uuid.UUID, actor: Admin, session: DB) -> None:
    api.delete_model(session, actor, model_id)


# ---------------------------------------------------------------- назначения помещений


class PurposeIn(BaseModel):
    version: int | None = None
    name: str | None = Field(default=None, max_length=150)
    surface: float | None = None
    norm: int | None = None
    note: str | None = Field(default=None, max_length=1000)
    position: int | None = None


@router.get("/purposes")
def list_purposes(_: AnyActor, session: DB, archived: bool = False) -> dict[str, Any]:
    return {"items": [api.purpose_view(p) for p in api.purposes(session, archived)]}


@router.post("/purposes", status_code=201)
def create_purpose(body: PurposeIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.purpose_view(api.create_purpose(session, actor, body.model_dump(exclude_none=True)))


@router.patch("/purposes/{purpose_id}")
def update_purpose(
    purpose_id: uuid.UUID, body: PurposeIn, actor: Admin, session: DB
) -> dict[str, Any]:
    return api.purpose_view(
        api.update_purpose(session, actor, purpose_id, body.model_dump(exclude_none=True))
    )


@router.post("/purposes/{purpose_id}/archive")
def archive_purpose(purpose_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return api.purpose_view(api.set_archived_purpose(session, actor, purpose_id, True))


@router.post("/purposes/{purpose_id}/unarchive")
def unarchive_purpose(purpose_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return api.purpose_view(api.set_archived_purpose(session, actor, purpose_id, False))


# ---------------------------------------------------------------- Excel (5.2.6)


@router.get("/export.xlsx")
def export(_: Admin, session: DB) -> Response:
    return Response(
        excel.export(session),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('каталог.xlsx')}"},
    )


@router.post("/import")
def load(file: UploadFile, actor: Admin, session: DB, apply: bool = False) -> dict[str, Any]:
    return excel.load(session, actor, file.file, apply)
