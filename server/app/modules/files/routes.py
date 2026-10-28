import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core import uploads
from app.core.auth import Admin, AnyActor
from app.core.db import DB
from app.core.errors import Forbidden
from app.modules.files import api

router = APIRouter(prefix="/api/files", tags=["files"])

UNDERLAY = "pdf,png,jpeg,webp"


def _limit(session: Session, request: Request) -> tuple[str, int]:
    # подложка этажа — PDF или картинка (5.1.4); без PDF — снимок при обходе (5.4.6)
    accept = request.query_params.get("accept", UNDERLAY).split(",")
    return api.upload_limit(session, "underlay" if "pdf" in accept else "photo")


Upload = Annotated[uploads.Upload, uploads.receive(_limit)]


@router.post("", status_code=201, openapi_extra=uploads.form())
def upload(actor: Admin, file: Upload, session: DB, accept: str = UNDERLAY) -> dict[str, Any]:
    kinds = {k for k in accept.split(",") if k in api.KINDS}
    record = api.store(session, actor, file.file, file.name or "файл", kinds, file.limit)
    return api.view(record)


@router.get("/{file_id}")
def download(file_id: uuid.UUID, actor: AnyActor, session: DB) -> FileResponse:
    # кроме администратора — только тот, кто видит, к чему файл относится (R-018 п. 3)
    if not api.may_read(session, actor, file_id):
        raise Forbidden()
    record = api.get(session, file_id)
    return FileResponse(api.path_of(record.sha256), media_type=record.content_type,
                        filename=record.name,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
