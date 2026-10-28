import os
import tempfile
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core import uploads
from app.core.auth import Admin
from app.core.db import DB
from app.modules.system import api as system
from app.modules.transfer import package

router = APIRouter(prefix="/api", tags=["transfer"])


@router.get("/buildings/{building_id}/transfer.zip")
def export(
    building_id: uuid.UUID, actor: Admin, session: DB, after: BackgroundTasks
) -> FileResponse:
    """Пакет здания для переноса на другую установку (ZIP)."""
    fd, path = tempfile.mkstemp(suffix=".zip", dir=package.uploads_dir())
    with os.fdopen(fd, "wb") as out:
        name = package.build(session, actor, building_id, out)
    after.add_task(os.unlink, path)
    return FileResponse(path, media_type="application/zip", filename=name)


PackageUpload = Annotated[uploads.Upload, uploads.receive(
    lambda session, _: system.upload_limit(session, "transfer"))]


@router.post("/transfer/check", openapi_extra=uploads.form())
def check(actor: Admin, file: PackageUpload, session: DB) -> dict[str, Any]:
    """Загрузить пакет и проверить: что заведётся, что совпало, какие номера заняты."""
    package._admin(actor)
    upload = package.receive(file.file)
    return package.check(session, actor, upload)


class ImportIn(BaseModel):
    upload_id: uuid.UUID
    name: str = Field(max_length=200)
    renumber: bool = False


@router.post("/transfer/import", status_code=202)
def start(body: ImportIn, actor: Admin, session: DB) -> dict[str, Any]:
    """Загрузить проверенный пакет — фоновой задачей, одной транзакцией."""
    return {"job_id": package.start(session, actor, body.upload_id, body.name, body.renumber)}
