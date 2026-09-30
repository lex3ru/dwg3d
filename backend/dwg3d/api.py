"""HTTP API.

Projects hold drawings; a drawing is one uploaded DWG/DXF, processed by the
build queue into a 3D model.

  GET/POST /api/projects                 projects (with their drawings) / new project
  GET/PATCH/DELETE /api/projects/{id}    one project; name, description
  POST /api/projects/{id}/drawings       multipart: file, name, config (optional JSON string)
  GET  /api/projects/{id}/audit          who changed what (?drawing=)
  GET  /api/drawings?project=            drawings (building switcher)
  GET/DELETE /api/drawings/{id}          status / progress / result
  POST /api/drawings/{id}/revision       multipart: a new revision of the DWG; floors,
                                         editor corrections, furniture and pins follow it
  GET/PUT /api/drawings/{id}/view        viewer settings: name, map binding, detail model
                                         alignment (no rebuild)
  POST/DELETE /api/drawings/{id}/detail, GET /api/drawings/{id}/detail.glb
                                         detailed model (GLB) shown over the generated one
  POST /api/drawings/{id}/rebuild        JSON config override (floors.items, layers...)
  GET  /api/drawings/{id}/files/...      model.glb, metadata.json, debug/*.png
  GET  /api/drawings/{id}/drawing.dxf|dwg  source drawing with the editor corrections
  GET/POST /api/drawings/{id}/placements, PATCH/DELETE .../placements/{rid},
  POST /api/drawings/{id}/placements:batch
                                         placed furniture row by row, with versions (409
                                         on concurrent changes); the same for /pins
  GET  /api/config/default               default config
  GET  /api/catalog                      furniture / equipment catalog (PostgreSQL)
  POST /api/catalog/items, PATCH /api/catalog/items/{id}, POST .../{id}/model (GLB),
  POST /api/catalog/categories, PATCH /api/catalog/categories/{id}
                                         catalog editing (catalog_admin)
  GET  /api/reports/equipment?project=&format=json|xlsx
                                         equipment specification (one or all projects)
  GET  /api/health                       converter availability, database, queue
  POST /api/auth/login, /api/auth/logout, GET /api/auth/me
                                         sign-in (session cookie), see auth.py

Run:  uvicorn dwg3d.api:app --port 8765 [--workers N]

Environment:
  DWG3D_DATA              data directory (default <project>/data): the files
                          themselves, or only working copies with S3 (files.py)
  DWG3D_S3_*              S3-compatible storage for the files (see files.py)
  DWG3D_DATABASE_URL      PostgreSQL (default: the docker compose service, see
                          dwg3d/db.py); migrated to the latest schema on start
  DWG3D_MAX_UPLOAD_MB     upload limit (200)
  DWG3D_WORKERS           build threads per API process (2; 0 = builds only in
                          separate `python -m dwg3d worker` processes)
  DWG3D_CORS_ORIGINS      comma-separated origins allowed cross-origin (none;
                          the built UI and the Vite dev proxy are same-origin)
  DWG3D_RETENTION_DAYS    delete projects not touched for N days (0 = keep forever)

Every /api request except health and sign-in needs a session (DWG3D_AUTH=off
disables this): reading needs any role, changes need "editor", catalog
changes "catalog_admin". Serve it over HTTPS (the session cookie is marked
Secure when the request came over HTTPS, X-Forwarded-Proto included). All
state is in PostgreSQL and the file store (a data directory or S3), so
several uvicorn processes and hosts can serve the same projects.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import urllib.parse
import uuid
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

from . import auth, catalog, db, files, reports, store, viewdata, worker
from .config import ConfigError, deep_merge, load_config, validate_config
from .convert import available_converters
from .edits import anchor_of
from .models import Drawing, Project
from .pipeline import render_debug

log = logging.getLogger("dwg3d.api")
ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD = int(os.environ.get("DWG3D_MAX_UPLOAD_MB", "200")) * 1024 * 1024
RETENTION_DAYS = float(os.environ.get("DWG3D_RETENTION_DAYS", "0"))

app = FastAPI(title="dwg3d")
if origins := [o.strip() for o in os.environ.get("DWG3D_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/me"}


def required_role(method: str, path: str) -> str:
    if method in ("GET", "HEAD", "OPTIONS"):
        return "viewer"
    return "catalog_admin" if path.startswith("/api/catalog") else "editor"


@app.middleware("http")
async def _authenticate(request: Request, call_next):
    """Resolve the session cookie; refuse /api requests without the role they need."""
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC:
        return await call_next(request)
    if not auth.enabled():
        me = auth.ANONYMOUS_ADMIN
    else:
        me = await run_in_threadpool(auth.resolve, request.cookies.get(auth.COOKIE))
        if me is None:
            return JSONResponse({"detail": "Войдите, чтобы продолжить", "login": True}, status_code=401)
    need = required_role(request.method, path)
    if not me.can(need):
        return JSONResponse({"detail": f"Недостаточно прав: нужна роль «{auth.ROLE_NAMES[need]}»"}, status_code=403)
    token = auth.current.set(me)
    try:
        return await call_next(request)
    finally:
        auth.current.reset(token)


# ------------------------------------------------------------- sign-in ---
_FAILS: dict[str, list[float]] = {}          # login attempts per client (this process)
FAIL_LIMIT, FAIL_WINDOW = 10, 600


@app.post("/api/auth/login")
def auth_login(v: dict, request: Request, response: Response):
    login_, password = v.get("login") if isinstance(v, dict) else None, v.get("password") if isinstance(v, dict) else None
    if not isinstance(login_, str) or not isinstance(password, str) or len(login_) > 80 or len(password) > 200:
        raise HTTPException(400, "Нужны логин и пароль")
    key = f"{request.client.host if request.client else ''}|{login_.strip().lower()}"
    now = time.time()
    recent = [t for t in _FAILS.get(key, []) if now - t < FAIL_WINDOW]
    if len(recent) >= FAIL_LIMIT:
        raise HTTPException(429, "Слишком много неудачных попыток. Попробуйте через несколько минут")
    res = auth.login(login_, password, request.headers.get("user-agent", ""))
    if res is None:
        _FAILS[key] = [*recent, now]
        raise HTTPException(401, "Неверный логин или пароль")
    _FAILS.pop(key, None)
    auth.purge_sessions()
    token, me = res
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(auth.COOKIE, token, max_age=int(auth.session_days() * 86400), httponly=True,
                        samesite="lax", secure=secure, path="/")
    return me.json()


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    if not auth.enabled():
        return auth.ANONYMOUS_ADMIN.json()
    me = auth.resolve(request.cookies.get(auth.COOKIE))
    if me is None:
        return JSONResponse({"detail": "Войдите, чтобы продолжить", "login": True}, status_code=401)
    return me.json()

_last_cleanup = 0.0


def _cleanup():
    """Delete projects untouched for RETENTION_DAYS (disabled when 0)."""
    global _last_cleanup
    if RETENTION_DAYS <= 0 or time.time() - _last_cleanup < 3600:
        return
    _last_cleanup = time.time()
    with db.session() as s:
        gone = store.delete_stale(s, RETENTION_DAYS)
    for did in gone:
        files.store().delete_prefix(files.drawing_key(did))
    if gone:
        log.info("%d drawing(s) of stale projects removed (retention %s days)", len(gone), RETENTION_DAYS)


def _init_db():
    try:
        db.migrate()
        catalog.ensure_seeded()
    except Exception as ex:
        raise RuntimeError(f"PostgreSQL недоступен ({db.database_url().rsplit('@', 1)[-1]}): {ex}. "
                           "Запустите `docker compose up -d db` или задайте DWG3D_DATABASE_URL") from ex


_init_db()
if auth.enabled() and not auth.has_users():
    log.warning("Нет ни одного пользователя: создайте его — python -m dwg3d user add LOGIN --role catalog_admin "
                "(или DWG3D_AUTH=off для сервера во внутренней сети)")
worker.start(int(os.environ.get("DWG3D_WORKERS", "2")))
_cleanup()


def _serve(key: str, media_type: str, filename: str | None = None, headers: dict | None = None):
    """A file of the store as the response: from disk, or streamed from S3."""
    st = files.store()
    if (p := st.local_path(key)) is not None:
        return FileResponse(p, media_type=media_type, filename=filename, headers=headers)
    size = st.size(key)
    if size is None:
        raise HTTPException(404)
    h = {"Content-Length": str(size), **(headers or {})}
    if filename:
        h["Content-Disposition"] = f"attachment; filename*=utf-8''{urllib.parse.quote(filename)}"
    return StreamingResponse(st.stream(key), media_type=media_type, headers=h)


def _tmp_path(suffix: str = "") -> Path:
    """A fresh local temp file path for an upload on its way into the store."""
    d = files.data_root() / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{uuid.uuid4().hex}{suffix}.part"


def _project(s, pid: str, lock: bool = False) -> Project:
    p = store.get_project(s, pid, lock=lock)
    if p is None:
        raise HTTPException(404, "Проект не найден")
    return p


def _drawing(s, did: str, lock: bool = False) -> Drawing:
    d = store.get_drawing(s, did, lock=lock)
    if d is None:
        raise HTTPException(404, "Чертёж не найден")
    return d


@app.get("/api/health")
def health():
    ok = db.ping()
    return {"ok": ok, "converters": available_converters(), "db": ok, "queue": worker.queue_stats() if ok else None}


@app.get("/api/catalog")
def get_catalog():
    return catalog.as_json()


# ------------------------------------------ catalog editing (catalog_admin) ---
MAX_CATALOG_GLB = int(os.environ.get("DWG3D_MAX_CATALOG_GLB_MB", "50")) * 1024 * 1024


@app.exception_handler(catalog.CatalogError)
def _catalog_invalid(_, ex: catalog.CatalogError):
    return JSONResponse({"detail": str(ex)}, status_code=400)


@app.post("/api/catalog/items", status_code=201)
def create_catalog_item(v: dict):
    return catalog.create_item(v)


@app.patch("/api/catalog/items/{iid}")
def update_catalog_item(iid: str, v: dict):
    return catalog.update_item(iid, v)


@app.post("/api/catalog/items/{iid}/model")
async def upload_catalog_model(iid: str, file: UploadFile = File(...)):
    data = await file.read(MAX_CATALOG_GLB + 1)
    if len(data) > MAX_CATALOG_GLB:
        raise HTTPException(413, "Файл слишком большой")
    return await run_in_threadpool(catalog.upload_model, iid, data)


@app.get("/api/catalog/models/{name}")
def get_catalog_model(name: str):
    key = catalog.model_key(name)
    if key is None:
        raise HTTPException(404)
    # file names carry a content hash: cache forever
    return _serve(key, "model/gltf-binary", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.post("/api/catalog/categories", status_code=201)
def create_catalog_category(v: dict):
    return catalog.save_category(v.get("id"), v, create=True)


@app.patch("/api/catalog/categories/{cid}")
def update_catalog_category(cid: str, v: dict):
    return catalog.save_category(cid, v, create=False)


# ------------------------------------------------------------- reports ---
@app.get("/api/reports/equipment")
def equipment_report(project: str | None = None, format: str = "json"):
    """Specification of one project (per floor) or of all projects (per project); format=xlsx for Excel."""
    if format not in ("json", "xlsx"):
        raise HTTPException(400, "format: json или xlsx")
    with db.session() as s:
        if project is not None:
            _project(s, project)
        rep = reports.equipment(s, project)
    if format == "json":
        return rep
    name = (f"Спецификация — {rep['project']['name']}" if project else "Сводная спецификация") + ".xlsx"
    quoted = urllib.parse.quote(name)
    return Response(reports.to_xlsx(rep),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=\"specification.xlsx\"; filename*=UTF-8''{quoted}"})


@app.get("/api/config/default")
def default_config():
    return load_config()


# ------------------------------------------------------------ projects ---
def _text(v: dict, key: str, n: int, required: bool = False) -> str | None:
    x = v.get(key)
    if x is None and not required:
        return None
    if not isinstance(x, str) or len(x.strip()) > n or (required and not x.strip()):
        raise HTTPException(400, f"{key}: строка до {n} символов" + (" (обязательно)" if required else ""))
    return x.strip()


@app.get("/api/projects")
def list_projects():
    with db.session() as s:
        return store.list_projects(s)


@app.post("/api/projects", status_code=201)
def create_project(v: dict):
    name = _text(v, "name", 200, required=True)
    with db.session() as s:
        me = auth.current.get()
        p = Project(id=uuid.uuid4().hex[:12], name=name, description=_text(v, "description", 5000) or "",
                    created_by=me.id if me else None)
        s.add(p)
        s.flush()
        viewdata.audit_entry(s, p.id, "project", p.id, "create", None, {"name": p.name})
        return store.project_json(s, p, [])


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    with db.session() as s:
        return store.project_json(s, _project(s, pid))


@app.patch("/api/projects/{pid}")
def update_project(pid: str, v: dict):
    with db.session() as s:
        p = _project(s, pid, lock=True)
        before, after = {}, {}
        for key, n, req in (("name", 200, True), ("description", 5000, False)):
            if key in v:
                x = _text(v, key, n, required=req) or ""
                if x != getattr(p, key):
                    before[key], after[key] = getattr(p, key), x
                    setattr(p, key, x)
        if after:
            p.updated_at = func.now()
            viewdata.audit_entry(s, p.id, "project", p.id, "update", before, after)
        s.flush()
        return store.project_json(s, p)


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str):
    """Hidden at once; rows and files go with the retention cleanup (or stay for recovery)."""
    with db.session() as s:
        p = _project(s, pid, lock=True)
        if any(store.has_active(s, d["id"]) for d in store.list_drawings(s, pid)):
            raise HTTPException(409, "Идёт обработка чертежа: удалите проект после её окончания")
        p.deleted_at = func.now()
        viewdata.audit_entry(s, p.id, "project", p.id, "delete", {"name": p.name}, None)


@app.get("/api/projects/{pid}/audit")
def get_audit(pid: str, limit: int = 100, drawing: str | None = None):
    with db.session() as s:
        _project(s, pid)
        return viewdata.audit(s, pid, limit, drawing)


# ------------------------------------------------------------ drawings ---
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


async def _save_upload(file: UploadFile, dst: Path) -> int:
    """Stream an upload to `dst` (removed again when it is too big)."""
    size = 0
    with open(dst, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, "Файл слишком большой")
            f.write(chunk)
    return size


@app.post("/api/projects/{pid}/drawings")
async def create_drawing(pid: str, file: UploadFile = File(...), config: str | None = Form(None),
                         name: str | None = Form(None)):
    filename, ext = _upload_name(file)
    override = _parse_config(config)
    if name is not None and len(name) > 200:
        raise HTTPException(400, "name: строка до 200 символов")
    with db.session() as s:
        _project(s, pid)
    _cleanup()
    did = uuid.uuid4().hex[:12]
    tmp = _tmp_path(ext)
    try:
        size = await _save_upload(file, tmp)
        await run_in_threadpool(files.store().put_file, files.drawing_key(did, f"input{ext}"), tmp, True)
        with db.session() as s:
            _project(s, pid, lock=True)
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


@app.post("/api/drawings/{did}/revision")
async def upload_revision(did: str, file: UploadFile = File(...)):
    """A new revision of the drawing's DWG: rebuilt with the same settings;
    floors are matched by their sheets, so corrections, furniture and pins
    stay on them (see store.sync_floors)."""
    filename, ext = _upload_name(file)
    with db.session() as s:
        _drawing(s, did)
        if store.has_active(s, did):
            raise HTTPException(409, "Чертёж ещё обрабатывается")
    tmp = _tmp_path(ext)
    try:
        size = await _save_upload(file, tmp)
        st = files.store()
        n = 1
        while st.size(files.drawing_key(did, f"input_r{n}{ext}")) is not None:
            n += 1
        name = f"input_r{n}{ext}"
        await run_in_threadpool(st.put_file, files.drawing_key(did, name), tmp, True)
    finally:
        tmp.unlink(missing_ok=True)
    with db.session() as s:
        d = _drawing(s, did, lock=True)
        if store.has_active(s, did):
            raise HTTPException(409, "Чертёж ещё обрабатывается")
        before = {"filename": d.filename, "size": d.size}
        d.filename, d.input_path, d.size = filename, name, size
        viewdata.audit_entry(s, d.project_id, "drawing", did, "revision", before,
                             {"filename": filename, "size": size}, did)
        job = store.enqueue(s, d)
        out = store.public(s, d, job)
    worker.wake()
    return out


@app.get("/api/drawings")
def list_drawings(project: str | None = None):
    """Drawings (of one project), newest first."""
    with db.session() as s:
        return store.list_drawings(s, project)


@app.delete("/api/drawings/{did}", status_code=204)
def delete_drawing(did: str):
    with db.session() as s:
        d = _drawing(s, did, lock=True)
        if store.has_active(s, did):
            raise HTTPException(409, "Чертёж ещё обрабатывается")
        d.deleted_at = func.now()
        store.touch_project(s, d.project_id)
        viewdata.audit_entry(s, d.project_id, "drawing", did, "delete", {"filename": d.filename}, None, did)


# ------------------------------------------------------ viewer settings ---
# Per-drawing viewer state that needs no rebuild. Map binding, detail-model
# alignment and the name are drawing columns; placed furniture, markers and
# comments are rows (viewdata.py), edited one by one through /api/drawings/{id}/placements
# and /pins or, for whole-list clients, through PUT /api/drawings/{id}/view.
MAX_DETAIL = int(os.environ.get("DWG3D_MAX_DETAIL_MB", "150")) * 1024 * 1024
_f, _s = viewdata.num, viewdata.string

# viewer data tied to the floors of the build it was made on
FLOOR_BOUND = ("furniture", "furniture_unplaced", "markers", "comments")


@app.exception_handler(viewdata.Invalid)
def _invalid(_, ex: viewdata.Invalid):
    return JSONResponse({"detail": str(ex)}, status_code=400)


@app.exception_handler(viewdata.Conflict)
def _conflict(_, ex: viewdata.Conflict):
    return JSONResponse({"detail": str(ex), "conflicts": ex.conflicts}, status_code=409)


@app.exception_handler(LookupError)
def _missing(_, ex: LookupError):
    return JSONResponse({"detail": "Чертёж не найден"}, status_code=404)


def validate_settings(v: dict, old: dict) -> dict:
    """name / site / detail from a PUT /view body: the columns to set."""
    out = {}
    if "name" in v:
        out["name"] = _s(v["name"], "name", 120)
    if "site" in v:
        st = v["site"]
        if st is None:
            out["site"] = None
        else:
            if not isinstance(st, dict):
                raise viewdata.Invalid("view.site: ожидается объект")
            out["site"] = {"lat": _f(st.get("lat"), -85, 85, "site.lat"), "lon": _f(st.get("lon"), -180, 180, "site.lon"),
                           "azimuth": _f(st.get("azimuth", 0), -360, 360, "site.azimuth"),
                           "scale": _f(st.get("scale", 1), 0.01, 100, "site.scale")}
            if st.get("tiles"):
                t = _s(st["tiles"], "site.tiles", 300)
                if not t.startswith("https://") or not all(k in t for k in ("{z}", "{x}", "{y}")):
                    raise viewdata.Invalid("view.site.tiles: шаблон https://…/{z}/{x}/{y}.png")
                out["site"]["tiles"] = t
                out["site"]["attribution"] = _s(st.get("attribution", ""), "site.attribution", 200)
    if "detail" in v:
        dt = v["detail"] or {}
        if not isinstance(dt, dict):
            raise viewdata.Invalid("view.detail: ожидается объект")
        cur = dict(old.get("detail") or {})
        if "offset" in dt:
            if not isinstance(dt["offset"], list) or len(dt["offset"]) != 3:
                raise viewdata.Invalid("view.detail.offset: ожидается [x, y, z]")
            cur["offset"] = [_f(c, -1e4, 1e4, "detail.offset") for c in dt["offset"]]
        if "rotation" in dt:
            cur["rotation"] = _f(dt["rotation"], -360, 360, "detail.rotation")
        if "scale" in dt:
            cur["scale"] = _f(dt["scale"], 1e-4, 1e4, "detail.scale")
        out["detail"] = cur
    return out


@app.get("/api/drawings/{did}/view")
def get_view(did: str):
    with db.session() as s:
        return store.view_of(s, _drawing(s, did))


@app.put("/api/drawings/{did}/view")
def put_view(did: str, v: dict):
    """Merge viewer settings: top-level keys given replace the stored ones.
    Whole furniture / pin lists are turned into row changes (last writer
    wins); the viewer edits rows through /api/drawings/{id}/placements instead."""
    with db.session() as s:
        d = _drawing(s, did, lock=True)
        if any(k in v for k in FLOOR_BOUND):
            # these refer to floors of a particular build: never write them across a rebuild
            if store.has_active(s, did):
                raise HTTPException(409, "Идёт перестроение модели: расстановка и метки сохранятся после него")
            if "_build" in v and v["_build"] != d.current_build:
                raise HTTPException(409, "Модель была перестроена: обновите страницу, чтобы не потерять изменения")
        cols = validate_settings(v, store.view_of(s, d))
        if cols:
            _audit_settings(s, d, cols)
            store.set_settings(d, cols)
        for k in ("furniture", "markers", "comments", "furniture_unplaced"):
            if k in v:
                viewdata.replace(s, did, k, v[k])
        s.flush()
        return store.view_of(s, d)


def _audit_settings(s, d: Drawing, cols: dict):
    before = {k: getattr(d, k) for k in cols}
    if before != cols:
        viewdata.audit_entry(s, d.project_id, "drawing", d.id, "update", before, cols, d.id)


# ----------------------------------------- furniture and pins, row by row ---
# Floors are the candidate ids of the build given in `build` (409 if the model
# was rebuilt since); updates and deletes carry the row `version` they were
# made against (409 with the current rows if someone changed them meanwhile).
ROW_KINDS = {"placements": "placement", "pins": "pin"}


def _body(v) -> dict:
    if not isinstance(v, dict):
        raise viewdata.Invalid("Ожидается объект")
    return v


def _one(res: dict):
    return res["items"][0] if res["items"] else None


def _row_routes(kind: str):
    entity = ROW_KINDS[kind]

    def list_rows(did: str, floor: str | None = None):
        with db.session() as s:
            d = _drawing(s, did)
            data = viewdata.view_data(s, did)
        pick = lambda k: [it for it in data.get(k) or [] if floor is None or it["floor"] == floor]  # noqa: E731
        if kind == "placements":
            return {"build": d.current_build, "items": pick("furniture"), "unplaced": data.get("furniture_unplaced") or []}
        return {"build": d.current_build, "markers": pick("markers"), "comments": pick("comments")}

    def batch_rows(did: str, v: dict):
        """{build, ops: [{op, id, version, ...}]}: all applied or none (Ряд…, копии, отмена)."""
        v = _body(v)
        with db.session() as s:
            return viewdata.apply(s, did, entity, v.get("ops"), build=v.get("build"))

    def create_row(did: str, v: dict):
        v = _body(v)
        with db.session() as s:
            return _one(viewdata.apply(s, did, entity, [{**v, "op": "create"}], build=v.get("build")))

    def update_row(did: str, rid: str, v: dict):
        v = _body(v)
        with db.session() as s:
            return _one(viewdata.apply(s, did, entity, [{**v, "op": "update", "id": rid}], build=v.get("build")))

    def delete_row(did: str, rid: str, version: int | None = None, build: int | None = None):
        with db.session() as s:
            viewdata.apply(s, did, entity, [{"op": "delete", "id": rid, "version": version}], build=build)

    base = f"/api/drawings/{{did}}/{kind}"
    app.add_api_route(base, list_rows, methods=["GET"])
    app.add_api_route(base + ":batch", batch_rows, methods=["POST"])
    app.add_api_route(base, create_row, methods=["POST"], status_code=201)
    app.add_api_route(base + "/{rid}", update_row, methods=["PATCH"])
    app.add_api_route(base + "/{rid}", delete_row, methods=["DELETE"], status_code=204)


for _kind in ROW_KINDS:
    _row_routes(_kind)


@app.post("/api/drawings/{did}/detail")
async def upload_detail(did: str, file: UploadFile = File(...)):
    """Detailed model (GLB: facade, furniture...) shown over the generated one."""
    with db.session() as s:
        _drawing(s, did)
    tmp = _tmp_path(".glb")
    size, head = 0, b""
    with open(tmp, "wb") as f:
        while chunk := await file.read(1 << 20):
            if not head:
                head = chunk[:12]
            size += len(chunk)
            if size > MAX_DETAIL:
                f.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "Файл слишком большой")
            f.write(chunk)
    if head[:4] != b"glTF" or int.from_bytes(head[4:8], "little") != 2:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, "Нужен файл GLB (glTF 2.0, бинарный)")
    await run_in_threadpool(files.store().put_file, files.drawing_key(did, "detail.glb"), tmp, True)
    with db.session() as s:
        p = _drawing(s, did, lock=True)
        d = dict(p.detail or {})
        d.update(file=Path(file.filename or "detail.glb").name[:200], size=size,
                 version=int(d.get("version", 0)) + 1)
        d.setdefault("offset", [0.0, 0.0, 0.0])
        d.setdefault("rotation", 0.0)
        d.setdefault("scale", 1.0)
        p.detail = d
        p.updated_at = func.now()
        return store.view_of(s, p)


@app.delete("/api/drawings/{did}/detail")
def delete_detail(did: str):
    with db.session() as s:
        p = _drawing(s, did, lock=True)
        files.store().delete(files.drawing_key(did, "detail.glb"))
        p.detail = None
        p.updated_at = func.now()
        return store.view_of(s, p)


@app.get("/api/drawings/{did}/detail.glb")
def get_detail(did: str):
    with db.session() as s:
        _drawing(s, did)
    return _serve(files.drawing_key(did, "detail.glb"), "model/gltf-binary")


@app.get("/api/drawings/{did}")
def get_drawing(did: str):
    with db.session() as s:
        return store.public(s, _drawing(s, did))


@app.post("/api/drawings/{did}/rebuild")
def rebuild(did: str, override: dict):
    if not isinstance(override, dict):
        raise HTTPException(400, "Ожидается объект")
    with db.session() as s:
        p = _drawing(s, did, lock=True)          # check + enqueue under the row lock: no double builds
        if store.has_active(s, did):
            raise HTTPException(409, "Задача ещё выполняется")
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


@app.get("/api/drawings/{did}/drawing.{fmt}")
def export_drawing(did: str, fmt: str):
    """Source drawing with the 2D-editor corrections applied (DXF or DWG)."""
    from .dxf_writer import dxf_to_dwg, export_edited_dxf, has_edits

    if fmt not in ("dxf", "dwg"):
        raise HTTPException(400, "Формат: dxf или dwg")
    with db.session() as s:
        p = _drawing(s, did)
        cfg, input_path, filename = p.config or {}, p.input_path, p.filename
    if not has_edits(cfg):
        raise HTTPException(400, "Правок нет — сохранять нечего")
    src_rel = input_path
    if Path(input_path).suffix.lower() == ".dwg":
        src_rel = f"out/{Path(input_path).stem}.dxf"
    stem = Path(filename).stem + "_правки"
    # cache per configuration (edits, layer mapping, floors) actually applied
    key = hashlib.sha1(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
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
                    export_edited_dxf(src, dxf, cfg)
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
    return _serve(ekey(out_name), media, filename=f"{stem}.{fmt}")


FILE_TYPES = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png",
              ".ifc": "application/x-step", ".zip": "application/zip"}


@app.get("/api/drawings/{did}/files/{path:path}")
def get_file(did: str, path: str):
    with db.session() as s:
        p = _drawing(s, did)
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
        return _serve(key, FILE_TYPES[ext], filename=f"{stem}{'_obj.zip' if ext == '.zip' else ext}")
    return _serve(key, FILE_TYPES[ext])


class _UI(StaticFiles):
    """Built frontend: index.html must be revalidated (it points to the
    current hashed bundle), hashed assets can be cached forever."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


_dist = ROOT / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", _UI(directory=_dist, html=True), name="ui")
