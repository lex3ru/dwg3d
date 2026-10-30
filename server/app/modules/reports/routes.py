import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse

from app.core.auth import Admin
from app.core.db import DB
from app.modules.reports import api, dump, home

router = APIRouter(prefix="/api", tags=["reports"])

MEDIA = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "dxf": "image/vnd.dxf",
}


@router.get("/reports")
def definitions(actor: Admin) -> dict[str, Any]:
    return {"items": api.definitions(actor)}


@router.get("/reports/{key}.{fmt}")
def build(key: str, fmt: str, request: Request, actor: Admin, session: DB) -> Response:
    params = {k: v for k, v in request.query_params.items()}
    base = str(request.base_url).rstrip("/")
    data, name = api.build(session, actor, key, fmt, params, base)
    return Response(
        data,
        media_type=MEDIA.get(fmt, "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/home")
def home_summary(building_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return home.summary(session, actor, building_id)


@router.get("/home/plan")
def home_plan(building_id: uuid.UUID, actor: Admin, session: DB) -> dict[str, Any]:
    return home.plan_checks(session, actor, building_id)


@router.post("/reports/exports", status_code=202)
def start_export(actor: Admin, session: DB, building_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Полная выгрузка (7.4): по зданию или по всем — фоновой задачей."""
    return {"job_id": dump.start(session, actor, building_id)}


@router.get("/reports/exports/{job_id}")
@router.head("/reports/exports/{job_id}")  # отдельно: у GET и HEAD в схеме API свои имена
def download_export(job_id: uuid.UUID, actor: Admin, session: DB) -> FileResponse:
    """HEAD — есть ли ещё архив: интерфейс спрашивает до скачивания, чтобы на удалённый
    архив показать сообщение, а не сбой загрузки в браузере (R-027)."""
    path, name = dump.export_file(session, actor, job_id)
    return FileResponse(path, media_type="application/zip", filename=name)
