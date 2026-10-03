"""HTTP API.

Projects hold drawings; a drawing is one uploaded DWG/DXF, processed by the
build queue into a 3D model.

  GET/POST /api/projects                 projects (with their drawings) / new project
  GET/PATCH/DELETE /api/projects/{id}    one project; name, description
  POST /api/projects/{id}/drawings       multipart: file, name, config (optional JSON string)
  GET  /api/projects/{id}/audit          who changed what (?drawing=)
  GET  /api/projects/{id}/events         changes as they happen (Server-Sent Events), see events.py
  POST /api/projects/{id}/ui-context     what a viewer window shows, for the user's agents (uicontext.py)
  GET  /api/drawings?project=            drawings (building switcher)
  GET/DELETE /api/drawings/{id}          status / progress / result
  POST /api/drawings/{id}/revision       multipart: a new revision of the DWG; floors,
                                         editor corrections, furniture and pins follow it
  GET/PUT /api/drawings/{id}/view        viewer settings: name, map binding, detail model
                                         alignment (no rebuild); GET also the objects and pins
  POST/DELETE /api/drawings/{id}/detail, GET /api/drawings/{id}/detail.glb
                                         detailed model (GLB) shown over the generated one
  POST /api/drawings/{id}/rebuild        JSON config override (floors.items, layers...)
  GET  /api/drawings/{id}/files/...      model.glb, metadata.json, debug/*.png
  GET  /api/drawings/{id}/drawing.dxf|dwg  source drawing with the editor corrections
  GET/POST /api/projects/{id}/layers, PATCH/DELETE .../layers/{lid}
                                         layers of a project (GET /api/layer-kinds: kinds)
  GET/POST /api/drawings/{id}/objects, PATCH/DELETE .../objects/{rid},
  POST /api/drawings/{id}/objects:batch  layer objects on the drawing's floors row by row, with
                                         versions (409 on concurrent changes); the same for /pins
  GET  /api/drawings/{id}/rooms          rooms (ids kept across builds)
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
  GET/POST /api/projects/{id}/agent-tokens, DELETE .../agent-tokens/{tid}
                                         tokens of AI agents (Authorization: Bearer), see tokens.py
  GET  /api/projects/{id}/proposals, GET /api/proposals/{pid}, POST .../apply, .../reject
                                         changes proposed by AI agents, see proposals.py
  /api/mcp                               MCP (Streamable HTTP) for AI agents with a token, see agent_mcp.py

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

import asyncio
import hashlib
import json
import logging
import os
import time
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route
from sqlalchemy import func, select

from . import (access, agent_mcp, auth, catalog, db, events, files, layers, proposals, reports, rooms, store, tokens,
               uicontext, viewdata, worker)
from .config import ConfigError, deep_merge, load_config, validate_config
from .convert import available_converters
from .edits import anchor_of
from .models import Drawing, Layer, LayerObject, Project, ProjectMember, Proposal
from .pipeline import render_debug

log = logging.getLogger("dwg3d.api")
ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD = int(os.environ.get("DWG3D_MAX_UPLOAD_MB", "200")) * 1024 * 1024
RETENTION_DAYS = float(os.environ.get("DWG3D_RETENTION_DAYS", "0"))



@asynccontextmanager
async def _lifespan(_):
    async with agent_mcp.running():
        yield


app = FastAPI(title="dwg3d", lifespan=_lifespan)
# MCP for AI agents (agent_mcp.py): first, before the UI's catch-all mount
app.router.routes.insert(0, Route(agent_mcp.PATH, endpoint=agent_mcp.Endpoint(), methods=["GET", "POST", "DELETE"]))
if origins := [o.strip() for o in os.environ.get("DWG3D_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout", "/api/auth/me"}
READ = ("GET", "HEAD", "OPTIONS")
# who is who: not for guests of share links
GUEST_DENIED = {"/api/users"}


def _whoami(request: Request) -> auth.Me | None:
    """The agent of a bearer token; else the user of the session cookie, else
    the guest of a share-link cookie. A token counts with sign-in off too:
    its limits hold anyway."""
    h = request.headers.get("authorization", "")
    if h[:7].lower() == "bearer ":
        return tokens.resolve(h[7:].strip())
    if not auth.enabled():
        return auth.ANONYMOUS_ADMIN
    return (auth.resolve(request.cookies.get(auth.COOKIE))
            or access.resolve_share(request.cookies.get(access.SHARE_COOKIE)))


@app.middleware("http")
async def _authenticate(request: Request, call_next):
    """Resolve the session (or share link); refuse /api requests of nobody,
    changes by guests and catalog changes without the catalog role. What a
    user may do in a project is checked by the endpoints (access.py)."""
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC or path.startswith("/api/share/"):
        return await call_next(request)
    me = await run_in_threadpool(_whoami, request)
    if me is None:
        return JSONResponse({"detail": "Войдите, чтобы продолжить", "login": True}, status_code=401)
    if path == agent_mcp.PATH and me.agent is None:
        return JSONResponse({"detail": "MCP — для ИИ-агентов: нужен токен (Authorization: Bearer dwg3d_…)"},
                            status_code=401)
    if me.share is not None and (request.method not in READ or path in GUEST_DENIED or path.startswith("/api/proposals/")
                                 or path.endswith(("/members", "/shares", "/audit", "/proposals"))):
        return JSONResponse({"detail": "Ссылка даёт доступ только для просмотра проекта"}, status_code=403)
    if me.agent is not None and not tokens.agent_may(request.method, path, me.agent["mode"]):
        return JSONResponse({"detail": f"Токен агента ({tokens.MODE_NAMES[me.agent['mode']]}) не даёт этого делать"},
                            status_code=403)
    if path.startswith("/api/catalog") and request.method not in READ and not me.can("catalog_admin"):
        return JSONResponse({"detail": "Недостаточно прав: нужна роль «администратор каталога»"}, status_code=403)
    token, mtoken = auth.current.set(me), auth.method.set(request.method)
    try:
        return await call_next(request)
    finally:
        auth.current.reset(token)
        auth.method.reset(mtoken)


@app.exception_handler(access.Denied)
def _denied(_, ex: access.Denied):
    return JSONResponse({"detail": str(ex)}, status_code=ex.status)


@app.exception_handler(auth.OIDCError)
def _oidc_failed(_, ex: auth.OIDCError):
    return JSONResponse({"detail": str(ex)}, status_code=400)


# ------------------------------------------------------------- sign-in ---
def _base_url(request: Request) -> str:
    """This site as the browser sees it (for redirects back from Keycloak)."""
    if url := os.environ.get("DWG3D_PUBLIC_URL"):
        return url.rstrip("/")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@app.get("/api/auth/login")
def auth_login(request: Request, next: str = "/"):
    """Off to the Keycloak sign-in page; it sends the browser back to /api/auth/callback."""
    if not auth.enabled():
        return RedirectResponse(auth.safe_next(next), status_code=303)
    url, state = auth.login_redirect(_base_url(request), next)
    r = RedirectResponse(url, status_code=303)
    r.set_cookie(auth.STATE_COOKIE, state, max_age=auth.STATE_TTL, httponly=True, samesite="lax",
                 secure=_secure(request), path="/api/auth")
    return r


@app.get("/api/auth/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                  error_description: str | None = None):
    if error or not code or not state:
        msg = error_description or error or "нет кода авторизации"
        return HTMLResponse(_signin_failed(msg), status_code=400)
    try:
        token, _, nxt = auth.complete_login(_base_url(request), code, state, request.cookies.get(auth.STATE_COOKIE),
                                            request.headers.get("user-agent", ""))
    except auth.OIDCError as ex:
        return HTMLResponse(_signin_failed(str(ex)), status_code=400)
    auth.purge_sessions()
    r = RedirectResponse(nxt, status_code=303)
    r.delete_cookie(auth.STATE_COOKIE, path="/api/auth")
    r.delete_cookie(access.SHARE_COOKIE, path="/")
    r.set_cookie(auth.COOKIE, token, max_age=int(auth.session_days() * 86400), httponly=True,
                 samesite="lax", secure=_secure(request), path="/")
    return r


def _signin_failed(msg: str) -> str:
    import html
    return ("<!doctype html><meta charset=utf-8><title>Вход не выполнен</title>"
            "<body style='font-family:sans-serif;max-width:40em;margin:4em auto'>"
            f"<h1>Вход не выполнен</h1><p>{html.escape(msg)}</p><p><a href='/'>Попробовать ещё раз</a></p>")


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    """End the session; `logout_url` signs out of Keycloak too (the browser goes there)."""
    url = auth.logout(request.cookies.get(auth.COOKIE), _base_url(request))
    response.delete_cookie(auth.COOKIE, path="/")
    response.delete_cookie(access.SHARE_COOKIE, path="/")
    return {"ok": True, "logout_url": url}


@app.get("/api/auth/me")
def auth_me(request: Request):
    me = _whoami(request)
    if me is None:
        return JSONResponse({"detail": "Войдите, чтобы продолжить", "login": True}, status_code=401)
    return me.json()


@app.post("/api/share/{token}")
def open_share(token: str, request: Request, response: Response):
    """Open a share link: the token goes into a cookie; the project to show."""
    me = access.resolve_share(token, touch=True)
    if me is None:
        raise HTTPException(404, "Ссылка недействительна: её отозвали, срок истёк или проект удалён")
    response.set_cookie(access.SHARE_COOKIE, token, max_age=30 * 86400, httponly=True, samesite="lax",
                        secure=_secure(request), path="/")
    return me.json()


@app.get("/api/users")
def search_users(q: str = "", limit: int = 20):
    """Users who have signed in at least once (to add them to a project)."""
    return auth.list_users(q[:100], limit)


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
if auth.enabled() and not os.environ.get("DWG3D_OIDC_ISSUER"):
    log.warning("Вход не настроен: задайте DWG3D_OIDC_ISSUER и DWG3D_OIDC_CLIENT_SECRET (Keycloak) "
                "или DWG3D_AUTH=off для сервера во внутренней сети")
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


def _project(s, pid: str, lock: bool = False, need: str | None = None) -> Project:
    """The project, if the current user may do this in it (`need`: the role
    it takes; by default viewer for reading, editor for changes)."""
    p = store.get_project(s, pid, lock=lock)
    if p is None:
        raise HTTPException(404, "Проект не найден")
    access.check(s, pid, need)
    return p


def _drawing(s, did: str, lock: bool = False, need: str | None = None) -> Drawing:
    d = store.get_drawing(s, did, lock=lock)
    if d is None:
        raise HTTPException(404, "Чертёж не найден")
    access.check_drawing(s, d, need)
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
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(data: bytes, name: str) -> Response:
    quoted = urllib.parse.quote(name + ".xlsx")
    return Response(data, media_type=XLSX, headers={
        "Content-Disposition": f"attachment; filename=\"specification.xlsx\"; filename*=UTF-8''{quoted}"})


@app.get("/api/reports/equipment")
def equipment_report(project: str | None = None, layer: str | None = None, by: str = "floor",
                     format: str = "json"):
    """Specification of one project (per floor, or room by room with by=room) or
    of all projects (per project); of one layer with `layer`; format=xlsx for Excel."""
    if format not in ("json", "xlsx"):
        raise HTTPException(400, "format: json или xlsx")
    if by not in ("floor", "room") or (by == "room" and project is None):
        raise HTTPException(400, "by: floor или room (room — только для проекта)")
    with db.session() as s:
        if project is not None:
            _project(s, project)
        if layer is not None and (project is None or _layer_of(s, project, layer) is None):
            raise HTTPException(404, "Слой не найден")
        me = auth.current.get()
        rep = (reports.by_room(s, project, layer, me, access.visible_layers(me)) if by == "room"
               else reports.equipment(s, project, layer, me, access.visible_layers(me)))
    if format == "json":
        return rep
    if by == "room":
        return _xlsx(reports.rooms_to_xlsx(rep), f"Спецификация по помещениям — {rep['project']['name']}")
    return _xlsx(reports.to_xlsx(rep), f"Спецификация — {rep['project']['name']}" if project else "Сводная спецификация")


@app.get("/api/projects/{pid}/checks")
def project_checks(pid: str):
    """Problems of the engineering layers: rooms short of fire detectors."""
    with db.session() as s:
        _project(s, pid)
        return {"fire": reports.fire_check(s, pid, auth.current.get())}


def _layer_of(s, pid: str, lid: str) -> Layer | None:
    return s.scalar(select(Layer).where(Layer.id == lid, Layer.project_id == pid))


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
    """The projects the user may open, with their drawings and the user's role."""
    with db.session() as s:
        return store.list_projects(s, auth.current.get())


@app.post("/api/projects", status_code=201)
def create_project(v: dict):
    name = _text(v, "name", 200, required=True)
    with db.session() as s:
        me = auth.current.get()
        p = Project(id=uuid.uuid4().hex[:12], name=name, description=_text(v, "description", 5000) or "",
                    created_by=me.id if me else None)
        s.add(p)
        s.flush()
        if me is not None and me.id is not None:           # the author owns it
            s.add(ProjectMember(project_id=p.id, user_id=me.id, role="owner", added_by=me.id))
        viewdata.audit_entry(s, p.id, "project", p.id, "create", None, {"name": p.name})
        return store.project_json(s, p, [], "owner")


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    with db.session() as s:
        p = _project(s, pid)
        return store.project_json(s, p, None, access.project_role(s, auth.current.get(), pid))


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
        return store.project_json(s, p, None, access.project_role(s, auth.current.get(), pid))


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str):
    """Hidden at once; rows and files go with the retention cleanup (or stay for recovery)."""
    with db.session() as s:
        p = _project(s, pid, lock=True, need="owner")
        if any(store.has_active(s, d["id"]) for d in store.list_drawings(s, pid)):
            raise HTTPException(409, "Идёт обработка чертежа: удалите проект после её окончания")
        p.deleted_at = func.now()
        viewdata.audit_entry(s, p.id, "project", p.id, "delete", {"name": p.name}, None)


@app.get("/api/projects/{pid}/audit")
def get_audit(pid: str, limit: int = 100, drawing: str | None = None):
    me = auth.current.get()
    if me is not None and me.share is not None:
        raise HTTPException(403, "Журнал изменений недоступен по ссылке")
    with db.session() as s:
        _project(s, pid)
        return viewdata.audit(s, pid, limit, drawing)


@app.get("/api/projects/{pid}/events")
async def project_events(pid: str, request: Request):
    """Changes in the project as they happen (Server-Sent Events, see events.py):
    `event: change` with what changed, or `entity: resync` — read everything
    again. Every HEARTBEAT seconds `event: ping` (windows reopen a stream that
    stays silent longer: a proxy may keep a dead one open), and the access is
    checked again (signed out, removed from the project, link or token revoked:
    the stream ends)."""
    def allowed() -> auth.Me | None:
        who = _whoami(request)
        with db.session() as s:
            return who if store.get_project(s, pid) is not None and access.project_role(s, who, pid) else None

    me = await run_in_threadpool(allowed)
    if me is None:
        raise HTTPException(404, "Проект не найден")
    q = events.subscribe(pid)

    def visible(ev: dict) -> dict | None:
        if "to_user" in ev:                 # a command to one user's windows (uicontext.py)
            mine = me.share is None and me.agent is None and me.id == ev["to_user"]
            return ev if mine else None
        if me.share is None:
            return ev
        # a guest: no names; only the drawings of the link
        drawings = me.share["drawings"]
        changes = [c for c in ev.get("changes", []) if drawings is None or c.get("drawing") in (None, *drawings)]
        return {"project": pid, "changes": changes, "more": ev.get("more", 0)} if "changes" in ev else ev

    async def stream():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), events.HEARTBEAT)
                except TimeoutError:
                    if await run_in_threadpool(allowed) is None:
                        return
                    yield "event: ping\ndata: {}\n\n"          # an event, not a comment: windows watch for it
                    continue
                ev = visible(ev)
                if ev is not None and "changes" not in ev or ev["changes"] or ev.get("more"):
                    yield f"event: change\ndata: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            events.unsubscribe(pid, q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@app.post("/api/projects/{pid}/ui-context", status_code=204)
def report_ui_context(pid: str, v: dict):
    """What this window shows ({client, drawing, floor, view, selected, room, proposal, tool}, or
    {client, closed: true}), for the user's agents (uicontext.py)."""
    me = auth.current.get()
    with db.session() as s:
        _project(s, pid, need="viewer")
        try:
            uicontext.report(s, pid, me.id if me else None, v.get("client"), v)
        except uicontext.ContextError as ex:
            raise HTTPException(400, str(ex))


# ------------------------------------------------ members and share links ---
def _bad(fn, *a):
    try:
        return fn(*a)
    except ValueError as ex:
        raise HTTPException(400, str(ex))
    except LookupError:
        raise HTTPException(404, "Не найдено")


@app.get("/api/projects/{pid}/members")
def list_members(pid: str):
    with db.session() as s:
        _project(s, pid)
        return access.members(s, pid)


@app.post("/api/projects/{pid}/members", status_code=201)
def add_member(pid: str, v: dict):
    """{who: login or e-mail, role}: an e-mail of someone who has not signed in yet is an invitation."""
    with db.session() as s:
        _project(s, pid, lock=True, need="owner")
        m = _bad(access.add_member, s, pid, v.get("who") or v.get("login") or v.get("email") or "", v.get("role"))
        viewdata.audit_entry(s, pid, "member", str(m["id"]), "create", None, m)
        return m


@app.patch("/api/projects/{pid}/members/{mid}")
def update_member(pid: str, mid: int, v: dict):
    with db.session() as s:
        _project(s, pid, lock=True, need="owner")
        m = _bad(access.set_member_role, s, pid, mid, v.get("role"))
        viewdata.audit_entry(s, pid, "member", str(mid), "update", None, m)
        return m


@app.delete("/api/projects/{pid}/members/{mid}", status_code=204)
def delete_member(pid: str, mid: int):
    with db.session() as s:
        _project(s, pid, lock=True, need="owner")
        m = _bad(access.remove_member, s, pid, mid)
        viewdata.audit_entry(s, pid, "member", str(mid), "delete", m, None)


@app.get("/api/projects/{pid}/shares")
def list_shares(pid: str):
    with db.session() as s:
        _project(s, pid, need="owner")
        return access.shares(s, pid)


@app.post("/api/projects/{pid}/shares", status_code=201)
def create_share(pid: str, v: dict, request: Request):
    """{name?, days?, drawings?, layers?} -> the link (its token is shown only now)."""
    with db.session() as s:
        _project(s, pid, lock=True, need="owner")
        x, token = _bad(access.create_share, s, pid, v if isinstance(v, dict) else {})
        viewdata.audit_entry(s, pid, "share", x["id"], "create", None, x)
    return {**x, "token": token, "url": f"{_base_url(request)}/#/s/{token}"}


@app.delete("/api/projects/{pid}/shares/{sid}")
def revoke_share(pid: str, sid: str):
    with db.session() as s:
        _project(s, pid, lock=True, need="owner")
        x = _bad(access.revoke_share, s, pid, sid)
        viewdata.audit_entry(s, pid, "share", sid, "revoke", None, x)
        return x


# ------------------------------------------------------ agents' proposals ---
@app.get("/api/projects/{pid}/proposals")
def list_proposals(pid: str, status: str | None = None, drawing: str | None = None, limit: int = 100):
    """Proposals of AI agents (newest first; ?status=open, ?drawing=)."""
    if status is not None and status not in proposals.STATUSES:
        raise HTTPException(400, f"status: {', '.join(proposals.STATUSES)}")
    with db.session() as s:
        _project(s, pid)
        return proposals.listing(s, pid, status, drawing, limit=limit)


def _proposal(s, prid: str, need: str | None = None) -> Proposal:
    p = s.scalar(select(Proposal).where(Proposal.id == prid).with_for_update())
    if p is None or store.get_drawing(s, p.drawing_id) is None:
        raise HTTPException(404, "Предложение не найдено")
    access.check(s, p.project_id, need, "Предложение не найдено")
    return p


def _proposal_out(s, p: Proposal) -> dict:
    return proposals.proposal_json(p, proposals._users(s, [p]), s.get(Drawing, p.drawing_id))


@app.get("/api/proposals/{prid}")
def get_proposal(prid: str):
    """The proposal and what it would do now (preview: created, updated {before, after},
    deleted rows); one that no longer applies turns stale here."""
    with db.session() as s:
        p = _proposal(s, prid, need="viewer")
        was = p.status
        pv = proposals.preview(s, p)
        if p.status != was:
            viewdata.audit_entry(s, p.project_id, "proposal", p.id, "stale", None, {"reason": p.reason}, p.drawing_id)
        return {**_proposal_out(s, p), "ops": p.ops, "preview": pv}


@app.post("/api/proposals/{prid}/apply")
def apply_proposal(prid: str):
    """Apply as the current user's change (an editor); 409 when it no longer applies (it turns stale)."""
    with db.session() as s:
        p = _proposal(s, prid, need="editor")
        try:
            res = proposals.apply(s, p)
        except viewdata.Conflict as ex:
            viewdata.audit_entry(s, p.project_id, "proposal", p.id, "stale", None, {"reason": p.reason}, p.drawing_id)
            out = JSONResponse({"detail": str(ex), "proposal": _proposal_out(s, p)}, status_code=409)
        else:
            viewdata.audit_entry(s, p.project_id, "proposal", p.id, "apply", None, {"summary": p.summary}, p.drawing_id)
            return {"proposal": _proposal_out(s, p), **res}
    return out


@app.post("/api/proposals/{prid}/reject")
def reject_proposal(prid: str, v: dict | None = None):
    """{reason?}: the agent sees it with proposal_status."""
    with db.session() as s:
        p = _proposal(s, prid, need="editor")
        reason = (v or {}).get("reason")
        proposals.reject(s, p, reason if isinstance(reason, str) else None)
        viewdata.audit_entry(s, p.project_id, "proposal", p.id, "reject", None, {"reason": p.reason}, p.drawing_id)
        return _proposal_out(s, p)


# --------------------------------------------------------- agent tokens ---
def _token_role(s, pid: str, need: str = "viewer") -> str:
    """The user's role in the project, for their tokens (not for guests)."""
    me = auth.current.get()
    if me is not None and me.share is not None:
        raise HTTPException(403, "Токены агентов недоступны по ссылке")
    _project(s, pid, need=need)
    return access.project_role(s, me, pid)


@app.get("/api/projects/{pid}/agent-tokens")
def list_agent_tokens(pid: str):
    """The user's tokens in the project (an owner: everyone's)."""
    with db.session() as s:
        role = _token_role(s, pid)
        return tokens.list_tokens(s, pid, auth.current.get(), role == "owner")


@app.post("/api/projects/{pid}/agent-tokens", status_code=201)
def create_agent_token(pid: str, v: dict):
    """{name?, mode: read | propose | write, days?} -> the token (shown only now)."""
    with db.session() as s:
        role = _token_role(s, pid)
        try:
            x, token = tokens.create(s, pid, v if isinstance(v, dict) else {}, role)
        except PermissionError as ex:
            raise HTTPException(403, str(ex))
        except ValueError as ex:
            raise HTTPException(400, str(ex))
        viewdata.audit_entry(s, pid, "agent_token", x["id"], "create", None, x)
    return {**x, "token": token}


@app.delete("/api/projects/{pid}/agent-tokens/{tid}")
def revoke_agent_token(pid: str, tid: str):
    with db.session() as s:
        role = _token_role(s, pid)
        x = _bad(tokens.revoke, s, pid, tid, role == "owner")
        viewdata.audit_entry(s, pid, "agent_token", tid, "revoke", None, x)
        return x


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
    """Drawings (of one project) the user may open, newest first."""
    with db.session() as s:
        return store.list_drawings(s, project, auth.current.get())


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
# comments are rows (viewdata.py), edited one by one through /api/drawings/{id}/objects
# and /pins.
MAX_DETAIL = int(os.environ.get("DWG3D_MAX_DETAIL_MB", "150")) * 1024 * 1024
_f, _s = viewdata.num, viewdata.string

# viewer data changed row by row, not through PUT /view
FLOOR_BOUND = ("furniture", "furniture_unplaced", "shapes", "markers", "comments")


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
    """Merge viewer settings (name, site, detail): the keys given replace the
    stored ones. Objects and pins change row by row (/objects, /pins)."""
    if any(k in v for k in FLOOR_BOUND):
        raise HTTPException(400, "Расстановка и метки меняются построчно: /objects и /pins")
    with db.session() as s:
        d = _drawing(s, did, lock=True)
        cols = validate_settings(v, store.view_of(s, d))
        if cols:
            _audit_settings(s, d, cols)
            store.set_settings(d, cols)
        s.flush()
        return store.view_of(s, d)


def _audit_settings(s, d: Drawing, cols: dict):
    before = {k: getattr(d, k) for k in cols}
    if before != cols:
        viewdata.audit_entry(s, d.project_id, "drawing", d.id, "update", before, cols, d.id)


# ------------------------------------------- objects and pins, row by row ---
# Floors are the candidate ids of the build given in `build` (409 if the model
# was rebuilt since); updates and deletes carry the row `version` they were
# made against (409 with the current rows if someone changed them meanwhile).
ROW_KINDS = {"objects": "object", "pins": "pin"}


def _body(v) -> dict:
    if not isinstance(v, dict):
        raise viewdata.Invalid("Ожидается объект")
    return v


def _one(res: dict):
    return res["items"][0] if res["items"] else None


def _row_routes(kind: str):
    entity = ROW_KINDS[kind]

    def list_rows(did: str, floor: str | None = None, layer: str | None = None):
        with db.session() as s:
            d = _drawing(s, did)
            data = viewdata.view_data(s, did, access.visible_layers(auth.current.get()))
        pick = lambda k: [it for it in data.get(k) or []  # noqa: E731
                          if (floor is None or it["floor"] == floor) and (layer is None or it.get("layer") == layer)]
        if kind == "objects":
            return {"build": d.current_build, "items": pick("furniture") + pick("shapes"),
                    "unplaced": [it for it in data.get("furniture_unplaced") or [] if layer is None or it["layer"] == layer]}
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


@app.get("/api/drawings/{did}/rooms")
def list_rooms(did: str):
    with db.session() as s:
        _drawing(s, did)
        return rooms.rooms_json(s, did)


# ---------------------------------------------------------------- layers ---
@app.exception_handler(layers.LayerError)
def _layer_invalid(_, ex: layers.LayerError):
    return JSONResponse({"detail": str(ex)}, status_code=400)


@app.get("/api/layer-kinds")
def layer_kinds():
    """{kinds, flows, flow_conflicts, zone_kinds, zone_forbidden}: layer kinds and the rules of routes and zones."""
    return layers.kinds_with_rules()


def _layer(s, pid: str, lid: str) -> Layer:
    layer = s.scalar(select(Layer).where(Layer.id == lid, Layer.project_id == pid).with_for_update())
    if layer is None:
        raise HTTPException(404, "Слой не найден")
    return layer


@app.get("/api/projects/{pid}/layers")
def list_layers(pid: str):
    with db.session() as s:
        _project(s, pid)
        shown = access.visible_layers(auth.current.get())
        return [x for x in layers.list_layers(s, pid) if shown is None or x["id"] in shown]


@app.post("/api/projects/{pid}/layers", status_code=201)
def create_layer(pid: str, v: dict):
    with db.session() as s:
        _project(s, pid, lock=True)
        layer = layers.create(s, pid, v)
        viewdata.audit_entry(s, pid, "layer", layer.id, "create", None, layers.layer_json(layer))
        store.touch_project(s, pid)
        return layers.layer_json(layer, 0)


@app.patch("/api/projects/{pid}/layers/{lid}")
def update_layer(pid: str, lid: str, v: dict):
    with db.session() as s:
        _project(s, pid)
        layer = _layer(s, pid, lid)
        me = auth.current.get()
        if me is not None and me.agent is not None and "locked" in v and v["locked"] != layer.locked:
            raise HTTPException(403, "Блокировку слоя меняет только человек")
        if "version" in v and v["version"] != layer.version:
            raise viewdata.Conflict("Слой изменён другим пользователем: обновите данные и повторите",
                                    [{"id": lid, "current": layers.layer_json(layer)}])
        changes = layers.update(layer, v)
        if changes:
            viewdata.audit_entry(s, pid, "layer", lid, "update", {k: b for k, (b, _) in changes.items()},
                                 {k: a for k, (_, a) in changes.items()})
            store.touch_project(s, pid)
        return layers.layer_json(layer)


@app.post("/api/projects/{pid}/layers/{lid}/copy", status_code=201)
def copy_layer(pid: str, lid: str, v: dict | None = None):
    """A copy of the layer with all its objects: a variant to compare with it."""
    with db.session() as s:
        _project(s, pid, lock=True)
        layer = _layer(s, pid, lid)
        copy = layers.copy_layer(s, layer, (v or {}).get("name"))
        viewdata.audit_entry(s, pid, "layer", copy.id, "create", None, {**layers.layer_json(copy), "copy_of": lid})
        store.touch_project(s, pid)
        n = s.scalar(select(func.count()).select_from(LayerObject).where(LayerObject.layer_id == copy.id))
        return layers.layer_json(copy, n)


@app.get("/api/projects/{pid}/layers/compare")
def compare_layers(pid: str, a: str, b: str):
    """Differences between two layers (variants): objects and the specification."""
    with db.session() as s:
        _project(s, pid)
        la, lb = _layer_of(s, pid, a), _layer_of(s, pid, b)
        if la is None or lb is None:
            raise HTTPException(404, "Слой не найден")
        shown = access.visible_layers(auth.current.get())
        if shown is not None and not {a, b} <= shown:
            raise HTTPException(404, "Слой не найден")
        return layers.compare(s, la, lb)


@app.delete("/api/projects/{pid}/layers/{lid}", status_code=204)
def delete_layer(pid: str, lid: str):
    """The layer and all its objects."""
    with db.session() as s:
        _project(s, pid)
        layer = _layer(s, pid, lid)
        if layer.locked:
            raise HTTPException(409, f"Слой «{layer.name}» заблокирован")
        viewdata.audit_entry(s, pid, "layer", lid, "delete", layers.layer_json(layer), None)
        s.delete(layer)
        store.touch_project(s, pid)


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


def _layers_payload(s, d: Drawing, which: str | None) -> dict | None:
    """The objects of project layers for the drawing export (see dxf_writer.add_project_layers):
    `which` — "none", "all" (default: the layers the user may see) or layer ids separated by commas."""
    from .models import CatalogItem
    from .shapes import CABLES, FLOWS, ZONE_KINDS

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


@app.get("/api/drawings/{did}/drawing.{fmt}")
def export_drawing(did: str, fmt: str, layers_: str | None = Query(None, alias="layers")):
    """Source drawing with the 2D-editor corrections applied and the objects of
    the project layers drawn in (DXF or DWG); ?layers=none|all|<id>,<id>."""
    from .dxf_writer import dxf_to_dwg, export_edited_dxf, has_edits

    if fmt not in ("dxf", "dwg"):
        raise HTTPException(400, "Формат: dxf или dwg")
    with db.session() as s:
        p = _drawing(s, did)
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
