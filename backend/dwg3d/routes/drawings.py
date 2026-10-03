"""Drawings: uploads and revisions, builds, the detail model, exports and build files."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from .. import access, auth, db, files, layers, store, viewdata, worker
from ..config import ConfigError, deep_merge, load_config, validate_config
from ..edits import anchor_of
from ..models import Drawing
from ..pipeline import render_debug
from . import common
from .common import cleanup, log, mb, save_upload, serve, tmp_path

router = APIRouter()
MAX_UPLOAD = mb("DWG3D_MAX_UPLOAD_MB", 200)
MAX_DETAIL = mb("DWG3D_MAX_DETAIL_MB", 150)


def _parse_config(config: str | None) -> dict:
    try:
        override = json.loads(config) if config else {}
    except json.JSONDecodeError:
        raise HTTPException(400, "config: некорректный JSON")
    if not isinstance(override, dict):
        raise HTTPException(400, "config: ожидается объект")
    try:
        validate_config(load_config(override))
    except ConfigError as ex:
        raise HTTPException(400, f"config: {ex}")
    return override


def _upload_name(file: UploadFile) -> tuple[str, str]:
    name = Path(file.filename or "plan.dwg").name
    ext = Path(name).suffix.lower()
    if ext not in (".dwg", ".dxf"):
        raise HTTPException(400, "Поддерживаются только .dwg и .dxf")
    return name, ext


def _idle(s, did: str, msg: str = "Чертёж ещё обрабатывается"):
    """409 while a build of the drawing is queued or running."""
    if store.has_active(s, did):
        raise HTTPException(409, msg)


@router.post("/api/projects/{pid}/drawings")
async def create_drawing(pid: str, file: UploadFile = File(...), config: str | None = Form(None),
                         name: str | None = Form(None)):
    filename, ext = _upload_name(file)
    override = _parse_config(config)
    if name is not None and len(name) > 200:
        raise HTTPException(400, "name: строка до 200 символов")
    with db.session() as s:
        common.project(s, pid)
    cleanup()
    did = uuid.uuid4().hex[:12]
    tmp = tmp_path(ext)
    try:
        size, _ = await save_upload(file, tmp, MAX_UPLOAD)
        await run_in_threadpool(files.store().put_file, files.drawing_key(did, f"input{ext}"), tmp, True)
        with db.session() as s:
            common.project(s, pid, lock=True)
            me = auth.current.get()
            d = Drawing(id=did, project_id=pid, name=(name or "").strip() or None, filename=filename,
                        input_path=f"input{ext}", size=size, config=override, created_by=me.id if me else None)
            s.add(d)
            s.flush()
            viewdata.audit_entry(s, pid, "drawing", did, "create", None, {"filename": filename}, did)
            job = store.enqueue(s, d)
            out = store.public(s, d, job)
    except BaseException:
        tmp.unlink(missing_ok=True)
        files.store().delete_prefix(files.drawing_key(did))
        raise
    worker.wake()
    return out


@router.post("/api/drawings/{did}/revision")
async def upload_revision(did: str, file: UploadFile = File(...)):
    """A new revision of the drawing's DWG: rebuilt with the same settings;
    floors are matched by their sheets, so corrections, furniture and pins
    stay on them (see store.sync_floors)."""
    filename, ext = _upload_name(file)
    with db.session() as s:
        common.drawing(s, did)
        _idle(s, did)
    tmp = tmp_path(ext)
    try:
        size, _ = await save_upload(file, tmp, MAX_UPLOAD)
        st = files.store()
        n = 1
        while st.size(files.drawing_key(did, f"input_r{n}{ext}")) is not None:
            n += 1
        name = f"input_r{n}{ext}"
        await run_in_threadpool(st.put_file, files.drawing_key(did, name), tmp, True)
    finally:
        tmp.unlink(missing_ok=True)
    with db.session() as s:
        d = common.drawing(s, did, lock=True)
        _idle(s, did)
        before = {"filename": d.filename, "size": d.size}
        d.filename, d.input_path, d.size = filename, name, size
        viewdata.audit_entry(s, d.project_id, "drawing", did, "revision", before,
                             {"filename": filename, "size": size}, did)
        job = store.enqueue(s, d)
        out = store.public(s, d, job)
    worker.wake()
    return out


@router.get("/api/drawings")
def list_drawings(project: str | None = None):
    """Drawings (of one project) the user may open, newest first."""
    with db.session() as s:
        return store.list_drawings(s, project, auth.current.get())


@router.delete("/api/drawings/{did}", status_code=204)
def delete_drawing(did: str):
    with db.session() as s:
        d = common.drawing(s, did, lock=True)
        _idle(s, did)
        d.deleted_at = func.now()
        store.touch_project(s, d.project_id)
        viewdata.audit_entry(s, d.project_id, "drawing", did, "delete", {"filename": d.filename}, None, did)


# ---------------------------------------------------------- detail model ---
@router.post("/api/drawings/{did}/detail")
async def upload_detail(did: str, file: UploadFile = File(...)):
    """Detailed model (GLB: facade, furniture...) shown over the generated one."""
    with db.session() as s:
        common.drawing(s, did)
    tmp = tmp_path(".glb")
    size, head = await save_upload(file, tmp, MAX_DETAIL)
    if head[:4] != b"glTF" or int.from_bytes(head[4:8], "little") != 2:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Нужен файл GLB (glTF 2.0, бинарный)")
    await run_in_threadpool(files.store().put_file, files.drawing_key(did, "detail.glb"), tmp, True)
    with db.session() as s:
        p = common.drawing(s, did, lock=True)
        d = dict(p.detail or {})
        d.update(file=Path(file.filename or "detail.glb").name[:200], size=size,
                 version=int(d.get("version", 0)) + 1)
        d.setdefault("offset", [0.0, 0.0, 0.0])
        d.setdefault("rotation", 0.0)
        d.setdefault("scale", 1.0)
        p.detail = d
        p.updated_at = func.now()
        return store.view_of(s, p)


@router.delete("/api/drawings/{did}/detail")
def delete_detail(did: str):
    with db.session() as s:
        p = common.drawing(s, did, lock=True)
        files.store().delete(files.drawing_key(did, "detail.glb"))
        p.detail = None
        p.updated_at = func.now()
        return store.view_of(s, p)


@router.get("/api/drawings/{did}/detail.glb")
def get_detail(did: str):
    with db.session() as s:
        common.drawing(s, did)
    return serve(files.drawing_key(did, "detail.glb"), "model/gltf-binary")


# ---------------------------------------------------------------- builds ---
@router.get("/api/drawings/{did}")
def get_drawing(did: str):
    with db.session() as s:
        return store.public(s, common.drawing(s, did))


@router.post("/api/drawings/{did}/rebuild")
def rebuild(did: str, override: dict):
    if not isinstance(override, dict):
        raise HTTPException(400, "Ожидается объект")
    with db.session() as s:
        p = common.drawing(s, did, lock=True)          # check + enqueue under the row lock: no double builds
        _idle(s, did, "Задача ещё выполняется")
        b = store.current_build(s, p)
        override = _anchor_override({"config": p.config, "result": b.result if b else {}}, override)
        # floors.items is replaced wholesale (a full assignment list), the rest is merged
        cfg = deep_merge(p.config or {}, override)
        try:
            validate_config(load_config(cfg))
        except ConfigError as ex:
            raise HTTPException(400, str(ex))
        p.config = cfg
        job = store.enqueue(s, p)
        out = store.public(s, p, job, b)
    worker.wake()
    return out


def _anchor_override(job: dict, override: dict) -> dict:
    """Edits and floor assignments refer to floor ids of the build the user
    looked at; pin them to that build's sheets and alignment (see edits.py)."""
    res = job.get("result") or {}
    floors = {f["id"]: f for f in res.get("floors") or []}
    cands = {c["id"]: c for c in res.get("candidates") or []}
    override = dict(override)
    if isinstance(override.get("edits"), dict):
        old = (job.get("config") or {}).get("edits") or {}
        new = {}
        for fid, e in override["edits"].items():
            if isinstance(e, dict):
                e = {k: v for k, v in e.items() if k != "_anchor"}
                if isinstance(old.get(fid), dict) and old[fid].get("_anchor"):
                    e["_anchor"] = old[fid]["_anchor"]
                elif fid in floors and floors[fid].get("bbox"):
                    e["_anchor"] = anchor_of(floors[fid])
            new[fid] = e
        override["edits"] = new
    items = (override.get("floors") or {}).get("items") if isinstance(override.get("floors"), dict) else None
    if isinstance(items, list):
        out = []
        for it in items:
            if isinstance(it, dict) and not it.get("_anchor") and str(it.get("candidate")) in cands:
                it = {**it, "_anchor": anchor_of(cands[str(it["candidate"])], with_offset=False)}
            out.append(it)
        override["floors"] = {**override["floors"], "items": out}
    return override


# ---------------------------------------------------------------- export ---
def _layers_payload(s, d: Drawing, which: str | None) -> dict | None:
    """The objects of project layers for the drawing export (see dxf_writer.add_project_layers):
    `which` — "none", "all" (default: the layers the user may see) or layer ids separated by commas."""
    from ..models import CatalogItem
    from ..shapes import CABLES, FLOWS, ZONE_KINDS

    if which == "none":
        return None
    shown = access.visible_layers(auth.current.get())
    wanted = None if which in (None, "", "all") else set(which.split(","))
    lays = [x for x in layers.list_layers(s, d.project_id)
            if (shown is None or x["id"] in shown) and (wanted is None or x["id"] in wanted)]
    ids = {x["id"] for x in lays}
    data = viewdata.view_data(s, d.id, ids)
    objs = [o for o in [*(data.get("furniture") or []), *(data.get("shapes") or [])] if o.get("layer") in ids]
    if not objs:
        return None
    used = {o["item"] for o in objs if o.get("item")}
    catalog_ = {i.id: {"id": i.id, "name": i.name, "w": i.w, "d": i.d, "h": i.h, "article": i.article or "",
                       **({"cam": i.camera} if i.camera else {})}
                for i in s.scalars(select(CatalogItem).where(CatalogItem.id.in_(used)))}
    return {"layers": [{"id": x["id"], "name": x["name"], "kind": x["kind"]} for x in lays if x["count"]],
            "objects": objs, "catalog": catalog_, "flows": FLOWS, "zone_kinds": ZONE_KINDS, "cables": CABLES}


@router.get("/api/drawings/{did}/drawing.{fmt}")
def export_drawing(did: str, fmt: str, layers_: str | None = Query(None, alias="layers")):
    """Source drawing with the 2D-editor corrections applied and the objects of
    the project layers drawn in (DXF or DWG); ?layers=none|all|<id>,<id>."""
    from ..dxf_writer import dxf_to_dwg, export_edited_dxf, has_edits

    if fmt not in ("dxf", "dwg"):
        raise HTTPException(400, "Формат: dxf или dwg")
    with db.session() as s:
        p = common.drawing(s, did)
        cfg, input_path, filename = p.config or {}, p.input_path, p.filename
        payload = _layers_payload(s, p, layers_)
    if not has_edits(cfg) and not payload:
        raise HTTPException(400, "Нет ни правок, ни объектов слоёв — сохранять нечего")
    src_rel = input_path
    if Path(input_path).suffix.lower() == ".dwg":
        src_rel = f"out/{Path(input_path).stem}.dxf"
    stem = Path(filename).stem + ("_правки" if has_edits(cfg) else "") + ("_слои" if payload else "")
    # cache per configuration (edits, layer mapping, floors) and layer objects actually applied
    key = hashlib.sha1(json.dumps([cfg, payload], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]
    st = files.store()
    ekey = lambda name: files.drawing_key(did, f"export/{key}/{name}")  # noqa: E731
    out_name, media = ("edited.dxf", "image/vnd.dxf") if fmt == "dxf" else ("edited.dwg", "application/acad")
    if st.size(ekey(out_name)) is None:
        if fmt == "dwg" and (err := st.get_bytes(ekey("edited.dwg.error"))) is not None:
            raise HTTPException(500, err.decode("utf-8"))   # don't re-run a slow converter that already failed
        try:
            with files.lock(did):
                wd = st.pull(did, paths=[src_rel])
                src = wd / src_rel
                if not src.exists():
                    raise HTTPException(409, "Чертёж ещё не обработан")
                cache = wd / "export" / key
                cache.mkdir(parents=True, exist_ok=True)
                dxf = cache / "edited.dxf"
                if not dxf.exists() and not st.download(ekey("edited.dxf"), dxf):
                    export_edited_dxf(src, dxf, cfg, payload)
                    st.put_file(ekey("edited.dxf"), dxf)
                if fmt == "dwg":
                    dwg = cache / "edited.dwg"
                    try:
                        dxf_to_dwg(dxf, dwg)
                    except Exception as ex:
                        st.put_bytes(ekey("edited.dwg.error"), str(ex).encode("utf-8"), "text/plain")
                        raise
                    st.put_file(ekey("edited.dwg"), dwg)
        except HTTPException:
            raise
        except Exception as ex:
            log.exception("drawing export failed")
            raise HTTPException(500, str(ex))
    return serve(ekey(out_name), media, filename=f"{stem}.{fmt}")


FILE_TYPES = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png",
              ".ifc": "application/x-step", ".zip": "application/zip"}


@router.get("/api/drawings/{did}/files/{path:path}")
def get_file(did: str, path: str):
    with db.session() as s:
        p = common.drawing(s, did)
        filename = p.filename
        busy = store.has_active(s, did)
    rel = PurePosixPath(path)
    ext = rel.suffix.lower()
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or ext not in FILE_TYPES \
            or rel.name == files.MANIFEST or rel.parts[0] == "cache":
        raise HTTPException(404)
    key = files.drawing_key(did, f"out/{rel}")
    st = files.store()
    if len(rel.parts) == 2 and rel.parts[0] == "debug" and ext == ".png" and not busy and st.size(key) is None:
        # rendered on demand from the cached plans
        with files.lock(did):
            wd = st.pull(did, trees=["out"], include=lambda r: r.startswith("cache/"))
            if (png := render_debug(wd / "out", rel.name)) is not None:
                st.put_file(key, png)
    if ext in (".ifc", ".zip"):
        stem = Path(filename).stem
        return serve(key, FILE_TYPES[ext], filename=f"{stem}{'_obj.zip' if ext == '.zip' else ext}")
    return serve(key, FILE_TYPES[ext])
