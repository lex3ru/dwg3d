"""Requests of the import service, under /api/import/v1 (contracts/openapi/import.v1.json).

A drawing is an uploaded DWG/DXF or a plan drawn in the 2D editor (kind «sketch», app/sketch.py): the
sketch is saved here whole and built on request, a copy of it going with the build.

Reading is for those who may see the plan of the building the drawing belongs
to, changes for its administrators (rights.py).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Body, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, insert, select, update
from twin_chassis import Identity, Problem, current_identity, emit, uuid7

from . import storage, store
from .dwg.config import ConfigError, deep_merge, load_config, validate_config
from .dwg.edits import anchor_of
from .models import builds, drawing_files, drawings
from .rights import manages_drawing, reads_build, reads_building, reads_drawing
from .sketch import SketchError, empty_sketch, read_sketch

router = APIRouter()
MAX_UPLOAD = int(os.environ.get("TWIN_MAX_UPLOAD_MB", "200")) * 1024 * 1024
BUSY = "Чертёж ещё обрабатывается"
SKETCH = "Это нарисованный план: он меняется в 2D-редакторе, а не файлом"
MAX_SKETCH_WALLS = 20000


# ------------------------------------------------------------------ helpers ---
def _checked(config: dict) -> dict:
    try:
        validate_config(load_config(config))
    except ConfigError as ex:
        raise Problem(422, "invalid", f"Настройки разбора: {ex}",
                      errors=[{"field": "config", "message": str(ex)}]) from ex
    return config


def _upload_name(file: UploadFile) -> str:
    name = Path(file.filename or "plan.dwg").name
    if Path(name).suffix.lower() not in (".dwg", ".dxf"):
        raise Problem(422, "invalid", "Поддерживаются только файлы .dwg и .dxf",
                      errors=[{"field": "file", "message": "Поддерживаются только .dwg и .dxf"}])
    return name


async def _receive(file: UploadFile, suffix: str) -> tuple[Path, int, str]:
    """The upload as a temporary file, its size and sha256."""
    digest, size = hashlib.sha256(), 0
    fd, name = tempfile.mkstemp(suffix=suffix, dir=storage.data_root())
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise Problem(413, "too_large", f"Файл больше {MAX_UPLOAD // (1024 * 1024)} МБ",
                                  title="Файл слишком большой")
                digest.update(chunk)
                await asyncio.to_thread(out.write, chunk)
        if size == 0:
            raise Problem(422, "invalid", "Файл пуст", errors=[{"field": "file", "message": "Файл пуст"}])
    except BaseException:
        tmp.unlink(missing_ok=True)     # noqa: ASYNC240 — a local temporary file
        raise
    return tmp, size, digest.hexdigest()


async def _drawing(session, drawing_id: UUID, *, lock: bool = False):
    d = await store.get_drawing(session, drawing_id, lock=lock)
    if d is None:
        raise Problem(404, "not_found", "Чертёж не найден")
    return d


def _file_only(d) -> None:
    if d.kind == "sketch":
        raise Problem(409, "sketch", SKETCH)


# ----------------------------------------------------------------- drawings ---
@router.post("/drawings", status_code=201, tags=["drawings"],
             summary="Загрузить чертёж в здание; сборка запускается сама")
async def create_drawing(request: Request, file: UploadFile = File(...), building_id: UUID = Form(...),
                         name: str | None = Form(None, max_length=200), config: str | None = Form(None),
                         me: Identity = Depends(current_identity)) -> dict:
    await request.app.state.rights.require(request, me, "manage", [("building", building_id)],
                                           what="Здание не найдено")
    filename = _upload_name(file)
    try:
        override = json.loads(config) if config else {}
    except json.JSONDecodeError as ex:
        raise Problem(422, "invalid", "config: некорректный JSON") from ex
    if not isinstance(override, dict):
        raise Problem(422, "invalid", "config: ожидается объект")
    _checked(override)
    tmp, size, sha = await _receive(file, Path(filename).suffix.lower())
    drawing_id, file_id = uuid7(), uuid7()
    key = storage.file_key(drawing_id, file_id, filename)
    try:
        await asyncio.to_thread(storage.bucket().put_file, key, tmp)
    finally:
        tmp.unlink(missing_ok=True)
    async with request.app.state.db.begin() as session:
        await session.execute(insert(drawings).values(id=drawing_id, building_id=building_id, name=(name or "").strip(),
                                                      config=override, created_by=me.sub))
        await store.add_file(session, drawing_id, file_id=file_id, filename=filename, size=size, sha256=sha,
                             storage_key=key, me=me)
        d = await _drawing(session, drawing_id)
        await store.enqueue(session, d, me)
        await emit(session, "import.drawing.uploaded", ("drawing", drawing_id),
                   {"drawing_id": str(drawing_id), "name": d.name or filename, "filename": filename, "file_n": 1},
                   building_id=building_id)
        return await store.drawing_json(session, d)


@router.post("/drawings/{drawing_id}/files", tags=["drawings"],
             summary="Новый файл чертежа; тот же файл повторно сборку не запускает")
async def upload_file(drawing_id: UUID, request: Request, file: UploadFile = File(...),
                      me: Identity = Depends(manages_drawing)) -> dict:
    filename = _upload_name(file)
    db = request.app.state.db
    async with db.begin() as session:
        d = await _drawing(session, drawing_id)
        _file_only(d)
        if await store.has_active_build(session, drawing_id):
            raise Problem(409, "busy", BUSY)
        current = (await session.execute(select(drawing_files).where(drawing_files.c.id == d.current_file_id))).one()
    tmp, size, sha = await _receive(file, Path(filename).suffix.lower())
    try:
        if sha == current.sha256:
            async with db.begin() as session:
                return {**await store.drawing_json(session, d), "unchanged": True}
        file_id = uuid7()
        key = storage.file_key(drawing_id, file_id, filename)
        await asyncio.to_thread(storage.bucket().put_file, key, tmp)
    finally:
        tmp.unlink(missing_ok=True)
    async with db.begin() as session:
        d = await _drawing(session, drawing_id, lock=True)
        if await store.has_active_build(session, drawing_id):
            raise Problem(409, "busy", BUSY)
        await store.add_file(session, drawing_id, file_id=file_id, filename=filename, size=size, sha256=sha,
                             storage_key=key, me=me)
        d = await _drawing(session, drawing_id)
        await store.enqueue(session, d, me)
        out = await store.drawing_json(session, d)
        await emit(session, "import.drawing.uploaded", ("drawing", drawing_id),
                   {"drawing_id": str(drawing_id), "name": out["name"], "filename": filename, "file_n": out["file_n"]},
                   building_id=d.building_id)
        return {**out, "unchanged": False}


@router.get("/drawings", tags=["drawings"], summary="Чертежи здания")
async def list_drawings(request: Request, building_id: UUID, _: Identity = Depends(reads_building)) -> dict:
    async with request.app.state.db.begin() as session:
        rows = (await session.execute(select(drawings).where(
            drawings.c.building_id == building_id, drawings.c.deleted_at.is_(None))
            .order_by(drawings.c.created_at))).all()
        return {"items": [await store.drawing_json(session, d) for d in rows]}


@router.get("/drawings/{drawing_id}", tags=["drawings"], summary="Чертёж и состояние его последней сборки")
async def get_drawing(drawing_id: UUID, request: Request, _: Identity = Depends(reads_drawing)) -> dict:
    async with request.app.state.db.begin() as session:
        return await store.drawing_json(session, await _drawing(session, drawing_id))


class DrawingPatch(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/drawings/{drawing_id}", tags=["drawings"], summary="Переименовать чертёж")
async def rename_drawing(drawing_id: UUID, body: DrawingPatch, request: Request,
                         _: Identity = Depends(manages_drawing)) -> dict:
    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id, lock=True)
        await session.execute(update(drawings).where(drawings.c.id == drawing_id)
                              .values(name=body.name.strip(), updated_at=func.now()))
        await emit(session, "import.drawing.renamed", ("drawing", drawing_id),
                   {"drawing_id": str(drawing_id), "name": body.name.strip()}, building_id=d.building_id)
        return await store.drawing_json(session, await _drawing(session, drawing_id))


@router.delete("/drawings/{drawing_id}", status_code=204, tags=["drawings"], summary="Удалить чертёж")
async def delete_drawing(drawing_id: UUID, request: Request, _: Identity = Depends(manages_drawing)) -> None:
    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id, lock=True)
        await session.execute(update(drawings).where(drawings.c.id == drawing_id).values(deleted_at=func.now()))
        await session.execute(update(builds).where(builds.c.drawing_id == drawing_id, builds.c.status == "queued")
                              .values(status="error", stage="error", error="Чертёж удалён", finished_at=func.now()))
        await emit(session, "import.drawing.deleted", ("drawing", drawing_id), {"drawing_id": str(drawing_id)},
                   building_id=d.building_id)


# ----------------------------------------------------------------- sketches ---
class SketchNew(BaseModel):
    building_id: UUID
    name: str = Field(default="", max_length=200)


@router.post("/sketches", status_code=201, tags=["sketches"],
             summary="Новый нарисованный план здания: пустой лист 2D-редактора; собирается по запросу")
async def create_sketch(body: SketchNew, request: Request, me: Identity = Depends(current_identity)) -> dict:
    await request.app.state.rights.require(request, me, "manage", [("building", body.building_id)],
                                           what="Здание не найдено")
    drawing_id = uuid7()
    name = body.name.strip() or "Нарисованный план"
    async with request.app.state.db.begin() as session:
        await session.execute(insert(drawings).values(
            id=drawing_id, building_id=body.building_id, name=name, kind="sketch",
            sketch=empty_sketch(uuid7().hex[-10:]), sketch_version=1, created_by=me.sub))
        await emit(session, "import.drawing.drawn", ("drawing", drawing_id),
                   {"drawing_id": str(drawing_id), "name": name}, building_id=body.building_id)
        return await store.drawing_json(session, await _drawing(session, drawing_id))


def _sketch_only(d) -> None:
    if d.kind != "sketch":
        raise Problem(409, "not_sketch", "Это загруженный чертёж, а не нарисованный план")


@router.get("/drawings/{drawing_id}/sketch", tags=["sketches"],
            summary="Нарисованный план (frontend/src/plan/model.ts) и номер его сохранения")
async def get_sketch(drawing_id: UUID, request: Request, me: Identity = Depends(reads_drawing)) -> dict:
    _no_guest(me)
    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id)
        _sketch_only(d)
        return {"sketch": d.sketch, "version": d.sketch_version}


class SketchSave(BaseModel):
    sketch: dict = Field(description="План целиком: version, floors (frontend/src/plan/model.ts)")
    version: int = Field(ge=0, description="Номер сохранения, с которого начаты правки")


@router.put("/drawings/{drawing_id}/sketch", tags=["sketches"],
            summary="Сохранить нарисованный план; правки поверх чужого сохранения — 409 conflict")
async def save_sketch(drawing_id: UUID, body: SketchSave, request: Request,
                      _: Identity = Depends(manages_drawing)) -> dict:
    try:
        sketch = read_sketch(body.sketch)
    except SketchError as ex:
        raise Problem(422, "invalid", f"План: {ex}", errors=[{"field": "sketch", "message": str(ex)}]) from ex
    if sum(len(f["walls"]) for f in sketch["floors"]) > MAX_SKETCH_WALLS:
        raise Problem(422, "invalid", f"В плане больше {MAX_SKETCH_WALLS} стен")
    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id, lock=True)
        _sketch_only(d)
        if body.version != d.sketch_version:
            raise Problem(409, "conflict", "План успели изменить в другом окне", extra={"version": d.sketch_version})
        await session.execute(update(drawings).where(drawings.c.id == drawing_id).values(
            sketch=sketch, sketch_version=d.sketch_version + 1, updated_at=func.now()))
        return {"version": d.sketch_version + 1}


# a picture of a plan to draw over, kept with the drawn plan
UNDERLAY_MAX = 20 * 1024 * 1024
UNDERLAY_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
UNDERLAY_NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp)$")


def _image_kind(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


@router.post("/drawings/{drawing_id}/underlays", status_code=201, tags=["sketches"],
             summary="Картинка-подложка нарисованного плана (PNG, JPEG, WebP до 20 МБ); в план её вписывает редактор")
async def upload_underlay(drawing_id: UUID, request: Request, file: UploadFile = File(...),
                          _: Identity = Depends(manages_drawing)) -> dict:
    async with request.app.state.db.begin() as session:
        _sketch_only(await _drawing(session, drawing_id))
    data = await file.read(UNDERLAY_MAX + 1)
    if len(data) > UNDERLAY_MAX:
        raise Problem(413, "too_large", "Картинка больше 20 МБ", title="Файл слишком большой")
    kind = _image_kind(data[:16])
    if kind is None:
        raise Problem(422, "invalid", "Подложкой может быть картинка PNG, JPEG или WebP",
                      errors=[{"field": "file", "message": "Нужна картинка PNG, JPEG или WebP"}])
    name = f"{uuid7().hex}.{kind}"
    await asyncio.to_thread(storage.bucket().put_bytes, storage.underlay_key(drawing_id, name), data,
                            UNDERLAY_TYPES[kind])
    return {"id": name, "size": len(data)}


@router.get("/drawings/{drawing_id}/underlays/{name}", tags=["sketches"], response_class=StreamingResponse,
            summary="Картинка-подложка нарисованного плана")
async def get_underlay(drawing_id: UUID, name: str, request: Request,
                       me: Identity = Depends(reads_drawing)) -> StreamingResponse:
    _no_guest(me)
    if not UNDERLAY_NAME.match(name):
        raise Problem(404, "not_found", "Файл не найден")
    async with request.app.state.db.begin() as session:
        _sketch_only(await _drawing(session, drawing_id))
    key = storage.underlay_key(drawing_id, name)
    size = await asyncio.to_thread(storage.bucket().size, key)
    if size is None:
        raise Problem(404, "not_found", "Файл не найден")
    headers = {"Content-Length": str(size), "Cache-Control": "private, max-age=31536000, immutable"}
    return StreamingResponse(iterate_in_threadpool(storage.bucket().stream(key)),
                             media_type=UNDERLAY_TYPES[name.rsplit(".", 1)[1]], headers=headers)


# ------------------------------------------------------------------- config ---
@router.get("/config/default", tags=["config"], summary="Настройки разбора по умолчанию")
async def default_config(_: Identity = Depends(current_identity)) -> dict:
    return load_config({})


@router.get("/drawings/{drawing_id}/config", tags=["config"],
            summary="Настройки разбора чертежа и правки 2D-редактора (config.edits)")
async def get_config(drawing_id: UUID, request: Request, me: Identity = Depends(reads_drawing)) -> dict:
    _no_guest(me)
    async with request.app.state.db.begin() as session:
        return {"config": (await _drawing(session, drawing_id)).config or {}}


def _anchor_override(config: dict, result: dict, override: dict) -> dict:
    """Corrections and floor assignments name floors by the ids of the build the
    user looked at; pin them to that build's sheets (app/dwg/edits.py), so they
    stay on their floors when ids change in later builds."""
    floors = {f["id"]: f for f in result.get("floors") or []}
    candidates = {c["id"]: c for c in result.get("candidates") or []}
    override = dict(override)
    if isinstance(override.get("edits"), dict):
        old, new = config.get("edits") or {}, {}
        for floor_id, e in override["edits"].items():
            if isinstance(e, dict):
                e = {k: v for k, v in e.items() if k != "_anchor"}
                if isinstance(old.get(floor_id), dict) and old[floor_id].get("_anchor"):
                    e["_anchor"] = old[floor_id]["_anchor"]
                elif floor_id in floors and floors[floor_id].get("bbox"):
                    e["_anchor"] = anchor_of(floors[floor_id])
            new[floor_id] = e
        override["edits"] = new
    items = (override.get("floors") or {}).get("items") if isinstance(override.get("floors"), dict) else None
    if isinstance(items, list):
        out = []
        for it in items:
            if isinstance(it, dict) and not it.get("_anchor") and str(it.get("candidate")) in candidates:
                it = {**it, "_anchor": anchor_of(candidates[str(it["candidate"])], with_offset=False)}
            out.append(it)
        override["floors"] = {**override["floors"], "items": out}
    return override


# ------------------------------------------------------------------- builds ---
@router.post("/drawings/{drawing_id}/builds", status_code=202, tags=["builds"],
             summary="Пересобрать чертёж, при необходимости изменив настройки и правки")
async def start_build(drawing_id: UUID, request: Request, body: dict = Body(default_factory=dict),
                      me: Identity = Depends(manages_drawing)) -> dict:
    override = body.get("config") or {}
    if not isinstance(override, dict):
        raise Problem(422, "invalid", "config: ожидается объект")
    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id, lock=True)        # check and enqueue under the lock: no double builds
        if await store.has_active_build(session, drawing_id):
            raise Problem(409, "busy", BUSY)
        if d.kind == "sketch":                                    # built as it is saved now; the editor saves first
            if not any(f["walls"] for f in (d.sketch or {}).get("floors") or []):
                raise Problem(422, "invalid", "В плане нет ни одной стены")
            await store.enqueue(session, d, me, sketch=d.sketch)
            return await store.drawing_json(session, await _drawing(session, drawing_id))
        result = {}
        if d.current_build_id:
            current = select(builds.c.result).where(builds.c.id == d.current_build_id)
            result = (await session.execute(current)).scalar() or {}
        # floors.items is replaced wholesale (a full assignment list), the rest is merged
        config = _checked(deep_merge(d.config or {}, _anchor_override(d.config or {}, result, override)))
        await session.execute(update(drawings).where(drawings.c.id == drawing_id)
                              .values(config=config, updated_at=func.now()))
        await store.enqueue(session, d, me)
        return await store.drawing_json(session, await _drawing(session, drawing_id))


async def _build(session, build_id: UUID):
    b = (await session.execute(select(builds).where(builds.c.id == build_id))).one_or_none()
    if b is None:
        raise Problem(404, "not_found", "Сборка не найдена")
    return b


@router.get("/builds/{build_id}", tags=["builds"], summary="Состояние сборки")
async def get_build(build_id: UUID, request: Request, _: Identity = Depends(reads_build)) -> dict:
    async with request.app.state.db.begin() as session:
        return store.build_json(await _build(session, build_id))


@router.get("/builds/{build_id}/result", tags=["builds"],
            summary="Результат сборки: этажи, помещения, входы, предупреждения")
async def get_result(build_id: UUID, request: Request, me: Identity = Depends(reads_build)) -> dict:
    _no_guest(me)
    async with request.app.state.db.begin() as session:
        b = await _build(session, build_id)
        if b.status != "done":
            raise Problem(409, "not_ready", "Сборка не завершена")
        d = (await session.execute(select(drawings).where(drawings.c.id == b.drawing_id))).one()
        return {"build": store.build_json(b), "building_id": str(d.building_id), "result": b.result}


def _no_guest(me: Identity) -> None:
    if me.kind == "guest":
        raise Problem(403, "guest", "Гостю по ссылке это недоступно")


async def _guest_model(request: Request, me: Identity, b, floor: UUID | None) -> str:
    """The model a guest of a floor or a room may have: their floor only, cut out of the drawing's model
    (and kept for the next guest). Which floor of the build that is, the buildings service says."""
    kind, _, building, own = me.guest
    if kind == "building":
        return f"{b.out_prefix}/model.glb"
    if floor is None or str(floor) != own:
        raise Problem(404, "not_found", "Файл не найден")
    token = request.headers.get("authorization", "").partition(" ")[2].strip()
    client = request.app.state.client
    plan, placed = await asyncio.gather(
        client.request("GET", "buildings", f"/floors/{floor}/plan", token=token),
        client.request("GET", "buildings", f"/buildings/{building}/drawings", token=token))
    if plan.status_code != 200 or placed.status_code != 200:
        raise Problem(404, "not_found", "Файл не найден")
    f = plan.json()["floor"]
    published = {d["id"]: d["build_id"] for d in placed.json()["items"]}
    if f["drawing_id"] != str(b.drawing_id) or published.get(f["drawing_id"]) != str(b.id) or not f.get("candidate"):
        raise Problem(404, "not_found", "Файл не найден")
    key = f"{b.out_prefix}/guest/floor_{f['candidate']}.glb"
    bucket = storage.bucket()
    if await asyncio.to_thread(bucket.size, key) is None:
        whole = await asyncio.to_thread(bucket.get_bytes, f"{b.out_prefix}/model.glb")
        if whole is None:
            raise Problem(404, "not_found", "Файл не найден")
        from .glb import cut
        await asyncio.to_thread(bucket.put_bytes, key, cut(whole, {f"floor_{f['candidate']}"}), storage.MEDIA[".glb"])
    return key


@router.get("/builds/{build_id}/files/{path:path}", tags=["builds"], response_class=StreamingResponse,
            summary="Файл сборки: model.glb, plans/floor_<id>.json, model.ifc, model_obj.zip")
async def get_build_file(build_id: UUID, path: str, request: Request, floor: UUID | None = None,
                         me: Identity = Depends(reads_build)) -> StreamingResponse:
    """A guest gets only the model, and a guest of a floor or a room — only their floor of it (`floor`)."""
    rel = PurePosixPath(path)
    media = storage.MEDIA.get(rel.suffix.lower())
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or media is None:
        raise Problem(404, "not_found", "Файл не найден")
    async with request.app.state.db.begin() as session:
        b = await _build(session, build_id)
    if me.kind == "guest":
        if rel.as_posix() != "model.glb" or not b.out_prefix:
            raise Problem(403, "guest", "Гостю по ссылке доступна только модель")
        key = await _guest_model(request, me, b, floor)
    else:
        key = f"{b.out_prefix}/{rel.as_posix()}" if b.out_prefix else None
    size = await asyncio.to_thread(storage.bucket().size, key) if key else None
    if size is None:
        raise Problem(404, "not_found", "Файл не найден")
    # the files of a build never change: the browser may keep them
    headers = {"Content-Length": str(size), "Cache-Control": "private, max-age=31536000, immutable"}
    if rel.suffix.lower() in (".ifc", ".zip", ".dxf"):
        headers["Content-Disposition"] = f'attachment; filename="{rel.name}"'
    return StreamingResponse(iterate_in_threadpool(storage.bucket().stream(key)), media_type=media, headers=headers)


class ObjectsExport(BaseModel):
    format: str = Field(default="dxf", pattern="^(dxf|dwg)$")
    objects: list[dict] = Field(max_length=20000, description="floor (id этажа в сборке), at [x, y], angle, type, "
                                "name, inventory_no, state, responsible, room, note")
    types: dict[str, dict] = Field(default_factory=dict, description="id типа → {id, w, d} в метрах")


@router.post("/drawings/{drawing_id}/export", tags=["export"], response_class=StreamingResponse,
             summary="Чертёж с объектами: блоки с атрибутами на своих местах (DXF или DWG)")
async def export_with_objects(drawing_id: UUID, body: ObjectsExport, request: Request,
                              _: Identity = Depends(manages_drawing)) -> StreamingResponse:
    from .export import drawing_with_objects

    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id)
        _file_only(d)
        f = (await session.execute(select(drawing_files).where(drawing_files.c.id == d.current_file_id))).one()
        b = None
        if d.current_build_id:
            b = (await session.execute(select(builds).where(builds.c.id == d.current_build_id))).one()
    if b is None:
        raise Problem(409, "not_ready", "Чертёж ещё не обработан")
    path, filename, stats = await asyncio.to_thread(drawing_with_objects, d, f, b, body.format, body.objects,
                                                    body.types)
    data = await asyncio.to_thread(path.read_bytes)
    shutil.rmtree(path.parent, ignore_errors=True)
    from urllib.parse import quote
    headers = {"Content-Length": str(len(data)), "X-Objects-Drawn": str(stats["drawn"]),
               "X-Objects-Skipped": str(stats["skipped"]),
               "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iter([data]), media_type=storage.MEDIA[f".{body.format}"], headers=headers)


# ------------------------------------------------------------------- export ---
@router.get("/drawings/{drawing_id}/export", tags=["export"], response_class=StreamingResponse,
            summary="Исходный чертёж с правками 2D-редактора: format=dxf или dwg")
async def export_drawing(drawing_id: UUID, request: Request, format: str = "dxf",
                         _: Identity = Depends(manages_drawing)) -> StreamingResponse:
    from .export import edited_drawing

    if format not in ("dxf", "dwg"):
        raise Problem(422, "invalid", "format: dxf или dwg", errors=[{"field": "format", "message": "dxf или dwg"}])
    async with request.app.state.db.begin() as session:
        d = await _drawing(session, drawing_id)
        _file_only(d)
        f = (await session.execute(select(drawing_files).where(drawing_files.c.id == d.current_file_id))).one()
        b = None
        if d.current_build_id:
            b = (await session.execute(select(builds).where(builds.c.id == d.current_build_id))).one()
    if b is None:
        raise Problem(409, "not_ready", "Чертёж ещё не обработан")
    key, filename = await asyncio.to_thread(edited_drawing, d, f, b, format)
    size = await asyncio.to_thread(storage.bucket().size, key)
    from urllib.parse import quote
    headers = {"Content-Length": str(size), "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    return StreamingResponse(iterate_in_threadpool(storage.bucket().stream(key)),
                             media_type=storage.MEDIA[f".{format}"], headers=headers)
