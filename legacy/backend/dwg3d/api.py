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
  GET  /api/projects/{id}/proposals, GET /api/proposals/{pid}, POST .../apply, .../reject
                                         changes proposed by the copilot, see proposals.py
  GET/PUT /api/copilot/settings, POST .../check, GET /api/copilot/status
  POST /api/projects/{id}/copilot, GET/DELETE .../copilot/chats[/{cid}]
                                         the built-in copilot (an external OpenAI-compatible model), see copilot.py

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
  DWG3D_ALLOW_WEAK_SECRETS  1: start even with the development secrets of
                          .env.example when DWG3D_PUBLIC_URL is not localhost
                          (otherwise the server refuses to start)

Every /api request except health and sign-in needs a session (DWG3D_AUTH=off
disables this): reading needs any role, changes need "editor", catalog
changes "catalog_admin". Serve it over HTTPS (the session cookie is marked
Secure when the request came over HTTPS, X-Forwarded-Proto included). All
state is in PostgreSQL and the file store (a data directory or S3), so
several uvicorn processes and hosts can serve the same projects.

This module is the app itself: sign-in middleware, error mapping, start-up
and the built UI; the endpoints are in routes/ (one router per area).
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import make_url

from . import access, auth, catalog, db, layers, viewdata, worker
from .convert import available_converters
from .routes import catalog as catalog_routes
from .routes import copilot as copilot_routes
from .routes import drawings as drawing_routes
from .routes import layers as layer_routes
from .routes import projects as project_routes
from .routes import reports as report_routes
from .routes import signin, view
from .routes.common import cleanup, log, whoami

ROOT = Path(__file__).resolve().parents[2]

app = FastAPI(title="dwg3d")
if origins := [o.strip() for o in os.environ.get("DWG3D_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])

PUBLIC = {"/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout", "/api/auth/me"}
READ = ("GET", "HEAD", "OPTIONS")
# who is who: not for guests of share links
GUEST_DENIED = {"/api/users"}


@app.middleware("http")
async def _authenticate(request: Request, call_next):
    """Resolve the session (or share link); refuse /api requests of nobody,
    changes by guests and catalog changes without the catalog role. What a
    user may do in a project is checked by the endpoints (access.py)."""
    path = request.url.path
    if not path.startswith("/api/") or path in PUBLIC or path.startswith("/api/share/"):
        return await call_next(request)
    me = await run_in_threadpool(whoami, request)
    if me is None:
        return JSONResponse({"detail": "Войдите, чтобы продолжить", "login": True}, status_code=401)
    if me.share is not None and (request.method not in READ or path in GUEST_DENIED or path.startswith("/api/proposals/")
                                 or path.endswith(("/members", "/shares", "/audit", "/proposals"))):
        return JSONResponse({"detail": "Ссылка даёт доступ только для просмотра проекта"}, status_code=403)
    if path.startswith("/api/catalog") and request.method not in READ and not me.can("catalog_admin"):
        return JSONResponse({"detail": "Недостаточно прав: нужна роль «администратор каталога»"}, status_code=403)
    token, mtoken = auth.current.set(me), auth.method.set(request.method)
    try:
        return await call_next(request)
    finally:
        auth.current.reset(token)
        auth.method.reset(mtoken)


# ------------------------------------------------------- errors as HTTP ---
def _detail(status: int):
    return lambda _, ex: JSONResponse({"detail": str(ex)}, status_code=status)


app.add_exception_handler(auth.OIDCError, _detail(400))
app.add_exception_handler(catalog.CatalogError, _detail(400))
app.add_exception_handler(layers.LayerError, _detail(400))
app.add_exception_handler(viewdata.Invalid, _detail(400))


@app.exception_handler(access.Denied)
def _denied(_, ex: access.Denied):
    return JSONResponse({"detail": str(ex)}, status_code=ex.status)


@app.exception_handler(viewdata.Conflict)
def _conflict(_, ex: viewdata.Conflict):
    return JSONResponse({"detail": str(ex), "conflicts": ex.conflicts}, status_code=409)


@app.exception_handler(LookupError)
def _missing(_, ex: LookupError):
    return JSONResponse({"detail": "Чертёж не найден"}, status_code=404)


# --------------------------------------------------------------- start-up ---
def _init_db():
    try:
        db.migrate()
        catalog.ensure_seeded()
    except Exception as ex:
        raise RuntimeError(f"PostgreSQL недоступен ({db.database_url().rsplit('@', 1)[-1]}): {ex}. "
                           "Запустите `docker compose up -d db` или задайте DWG3D_DATABASE_URL") from ex


DEV_SECRETS = {   # the values of .env.example: known to everyone
    "DWG3D_SECRET": "dev-secret-change-me",
    "DWG3D_OIDC_CLIENT_SECRET": "dev-client-secret",
    "DWG3D_S3_SECRET_KEY": "dwg3d-secret",
}


def weak_secrets() -> list[str]:
    """Settings left at the published development values (or too short to sign with)."""
    weak = [k for k, v in DEV_SECRETS.items() if os.environ.get(k) == v]
    if 0 < len(os.environ.get("DWG3D_SECRET", "")) < 32 and "DWG3D_SECRET" not in weak:
        weak.append("DWG3D_SECRET")
    if make_url(db.database_url()).password == "dwg3d":
        weak.append("POSTGRES_PASSWORD")
    return weak


def _local_site() -> bool:
    """The site is opened on this machine only (DWG3D_PUBLIC_URL unset or localhost)."""
    host = urlparse(os.environ.get("DWG3D_PUBLIC_URL") or "http://localhost").hostname or ""
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".localhost")


def _check_secrets():
    """Refuse to serve a site reachable by others with the development secrets
    (DWG3D_ALLOW_WEAK_SECRETS=1 for a test stand); on localhost only warn."""
    if not (weak := weak_secrets()):
        return
    msg = (f"Небезопасные значения по умолчанию: {', '.join(weak)}. Задайте свои в .env "
           "(deploy/make-env.sh создаёт .env со случайными паролями)")
    if _local_site() or os.environ.get("DWG3D_ALLOW_WEAK_SECRETS") == "1":
        log.warning(msg)
    else:
        raise RuntimeError(f"{msg}; сервер для {os.environ['DWG3D_PUBLIC_URL']} не запущен")


_check_secrets()
_init_db()
if auth.enabled() and not os.environ.get("DWG3D_OIDC_ISSUER"):
    log.warning("Вход не настроен: задайте DWG3D_OIDC_ISSUER и DWG3D_OIDC_CLIENT_SECRET (Keycloak) "
                "или DWG3D_AUTH=off для сервера во внутренней сети")
worker.start(int(os.environ.get("DWG3D_WORKERS", "2")))
cleanup()


@app.get("/api/health")
def health():
    ok = db.ping()
    return {"ok": ok, "converters": available_converters(), "db": ok, "queue": worker.queue_stats() if ok else None}


for _r in (signin, catalog_routes, report_routes, project_routes, copilot_routes, drawing_routes, view, layer_routes):
    app.include_router(_r.router)


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
