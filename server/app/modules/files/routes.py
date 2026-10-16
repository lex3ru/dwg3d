import uuid
from typing import Any

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse

from app.core.auth import Admin, AnyActor
from app.core.db import DB
from app.core.errors import Forbidden
from app.modules.files import api

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("", status_code=201)
def upload(file: UploadFile, actor: Admin, session: DB, accept: str = "pdf,png,jpeg,webp"
           ) -> dict[str, Any]:
    kinds = {k for k in accept.split(",") if k in api.KINDS}
    record = api.store(session, actor, file.file, file.filename or "файл", kinds)
    return api.view(record)


@router.get("/{file_id}")
def download(file_id: uuid.UUID, actor: AnyActor, session: DB) -> FileResponse:
    # ключ файла неугадываем; права на то, к чему файл относится, проверяет модуль-владелец,
    # выдавая ссылку на файл; гостю — только файлы плана и 3D
    if actor.is_guest and not api.guest_may(session, actor, file_id):
        raise Forbidden()
    record = api.get(session, file_id)
    return FileResponse(api.path_of(record.sha256), media_type=record.content_type,
                        filename=record.name,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
