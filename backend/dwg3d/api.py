"""HTTP API: upload DWG/DXF -> queued processing -> glTF + metadata.

  POST /api/jobs                 multipart: file, config (optional JSON string)
  GET  /api/jobs                 projects (building switcher)
  GET  /api/jobs/{id}            status / progress / result
  GET/PUT /api/jobs/{id}/view    viewer settings: map binding, detail model
                                 alignment, markers, comments, furniture
                                 (no rebuild)
  POST/DELETE /api/jobs/{id}/detail, GET /api/jobs/{id}/detail.glb
                                 detailed model (GLB) shown over the generated one
  POST /api/jobs/{id}/rebuild    JSON config override (floors.items, layers...)
  GET  /api/jobs/{id}/files/...  model.glb, metadata.json, debug/*.png
  GET  /api/config/default       default config
  GET  /api/catalog              furniture / equipment catalog (PostgreSQL)
  GET  /api/health               converter availability, database, queue

"Job" in the URLs is a project (a building): its id is the project id.

Run:  uvicorn dwg3d.api:app --port 8765 [--workers N]

Environment:
  DWG3D_DATA              data directory (default <project>/data)
  DWG3D_DATABASE_URL      PostgreSQL (default: the docker compose service, see
                          dwg3d/db.py); migrated to the latest schema on start
  DWG3D_MAX_UPLOAD_MB     upload limit (200)
  DWG3D_WORKERS           build threads per API process (2; 0 = builds only in
                          separate `python -m dwg3d worker` processes)
  DWG3D_CORS_ORIGINS      comma-separated origins allowed cross-origin (none;
                          the built UI and the Vite dev proxy are same-origin)
  DWG3D_RETENTION_DAYS    delete projects not touched for N days (0 = keep forever)

There is no authentication: bind to 127.0.0.1 or put it behind a reverse
proxy that authenticates. All state is in PostgreSQL and <DWG3D_DATA>, so
several uvicorn processes (and hosts sharing the data directory) can serve
the same projects.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

from . import catalog, db, store, worker
from .config import ConfigError, deep_merge, load_config, validate_config
from .convert import available_converters
from .edits import anchor_of
from .models import Project
from .pipeline import render_debug

log = logging.getLogger("dwg3d.api")
ROOT = Path(__file__).resolve().parents[2]
MAX_UPLOAD = int(os.environ.get("DWG3D_MAX_UPLOAD_MB", "200")) * 1024 * 1024
RETENTION_DAYS = float(os.environ.get("DWG3D_RETENTION_DAYS", "0"))

app = FastAPI(title="dwg3d")
if origins := [o.strip() for o in os.environ.get("DWG3D_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"])

_last_cleanup = 0.0


def _cleanup():
    """Delete projects untouched for RETENTION_DAYS (disabled when 0)."""
    global _last_cleanup
    if RETENTION_DAYS <= 0 or time.time() - _last_cleanup < 3600:
        return
    _last_cleanup = time.time()
    with db.session() as s:
        gone = store.delete_stale(s, RETENTION_DAYS)
    for pid in gone:
        shutil.rmtree(store.project_dir(pid), ignore_errors=True)
        log.info("project %s removed (retention %s days)", pid, RETENTION_DAYS)


def _init_db():
    try:
        db.migrate()
        catalog.ensure_seeded()
    except Exception as ex:
        raise RuntimeError(f"PostgreSQL недоступен ({db.database_url().rsplit('@', 1)[-1]}): {ex}. "
                           "Запустите `docker compose up -d db` или задайте DWG3D_DATABASE_URL") from ex


_init_db()
store.data_dir().mkdir(parents=True, exist_ok=True)
worker.start(int(os.environ.get("DWG3D_WORKERS", "2")))
_cleanup()


def _project(s, jid: str, lock: bool = False) -> Project:
    p = store.get_project(s, jid, lock=lock)
    if p is None:
        raise HTTPException(404, "Задача не найдена")
    return p


@app.get("/api/health")
def health():
    ok = db.ping()
    return {"ok": ok, "converters": available_converters(), "db": ok, "queue": worker.queue_stats() if ok else None}


@app.get("/api/catalog")
def get_catalog():
    return catalog.as_json()


@app.get("/api/config/default")
def default_config():
    return load_config()


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), config: str | None = Form(None)):
    name = Path(file.filename or "plan.dwg").name
    ext = Path(name).suffix.lower()
    if ext not in (".dwg", ".dxf"):
        raise HTTPException(400, "Поддерживаются только .dwg и .dxf")
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
    _cleanup()
    jid = uuid.uuid4().hex[:12]
    jdir = store.project_dir(jid)
    jdir.mkdir(parents=True)
    size = 0
    with open(jdir / f"input{ext}", "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                shutil.rmtree(jdir, ignore_errors=True)
                raise HTTPException(413, "Файл слишком большой")
            f.write(chunk)
    try:
        with db.session() as s:
            p = Project(id=jid, filename=name, input_path=f"input{ext}", size=size, config=override, view={})
            s.add(p)
            s.flush()
            job = store.enqueue(s, p)
            out = store.public(s, p, job)
    except Exception:
        shutil.rmtree(jdir, ignore_errors=True)
        raise
    worker.wake()
    return out


@app.get("/api/jobs")
def list_jobs():
    """Processed buildings (for the building switcher), newest first."""
    with db.session() as s:
        return store.list_projects(s)


# ------------------------------------------------------ viewer settings ---
# Per-job viewer state that needs no rebuild: map binding, detail-model
# alignment, user markers and comments, placed furniture. Stored in the project row.
MAX_PINS = 500
MAX_FURNITURE = 5000
MAX_DETAIL = int(os.environ.get("DWG3D_MAX_DETAIL_MB", "150")) * 1024 * 1024


def _f(v, lo, hi, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise HTTPException(400, f"view.{name}: ожидается число в [{lo}, {hi}]")
    return float(v)


def _s(v, name, n=2000):
    if not isinstance(v, str) or len(v) > n:
        raise HTTPException(400, f"view.{name}: ожидается строка до {n} символов")
    return v


def _pins(items, name):
    if not isinstance(items, list) or len(items) > MAX_PINS:
        raise HTTPException(400, f"view.{name}: ожидается список до {MAX_PINS} элементов")
    out = []
    for it in items:
        if not isinstance(it, dict) or not isinstance(it.get("pos"), list) or len(it["pos"]) != 3:
            raise HTTPException(400, f"view.{name}: элемент {{id, pos: [x, y, z], text}}")
        out.append({"id": _s(it.get("id", uuid.uuid4().hex[:8]), f"{name}.id", 40),
                    "floor": _s(it.get("floor") or "", f"{name}.floor", 40),
                    "pos": [_f(c, -1e5, 1e5, f"{name}.pos") for c in it["pos"]],
                    "text": _s(it.get("text", ""), f"{name}.text"),
                    "label": _s(it.get("label", ""), f"{name}.label", 8),
                    "author": _s(it.get("author", ""), f"{name}.author", 80),
                    "created": _f(it.get("created", time.time()), 0, 1e11, f"{name}.created")})
    return out


def _furniture(items):
    """Placed furniture / equipment: catalog item id, plan position (m), turn
    (degrees, counter-clockwise), optional size override [w, d, h] (m),
    mounting height; for CCTV cameras the view angle (deg) and range (m)."""
    if not isinstance(items, list) or len(items) > MAX_FURNITURE:
        raise HTTPException(400, f"view.furniture: ожидается список до {MAX_FURNITURE} элементов")
    out = []
    for it in items:
        if (not isinstance(it, dict) or not isinstance(it.get("at"), list) or len(it["at"]) != 2
                or not isinstance(it.get("item"), str)):
            raise HTTPException(400, "view.furniture: элемент {id, floor, item, at: [x, y], angle}")
        f = {"id": _s(it.get("id") or uuid.uuid4().hex[:8], "furniture.id", 40),
             "floor": _s(it.get("floor") or "", "furniture.floor", 40),
             "item": _s(it["item"], "furniture.item", 80),
             "at": [_f(c, -1e5, 1e5, "furniture.at") for c in it["at"]],
             "angle": _f(it.get("angle", 0), -3600, 3600, "furniture.angle") % 360}
        if it.get("size") is not None:
            if not isinstance(it["size"], list) or len(it["size"]) != 3:
                raise HTTPException(400, "view.furniture.size: ожидается [ширина, глубина, высота]")
            f["size"] = [_f(c, 0.01, 50, "furniture.size") for c in it["size"]]
        if it.get("note"):
            f["note"] = _s(it["note"], "furniture.note", 500)
        if it.get("elev") is not None:                  # mounting height override
            f["elev"] = _f(it["elev"], 0, 20, "furniture.elev")
        if it.get("fov") is not None:                   # CCTV camera: view angle, range
            f["fov"] = _f(it["fov"], 1, 360, "furniture.fov")
        if it.get("range") is not None:
            f["range"] = _f(it["range"], 0.5, 300, "furniture.range")
        out.append(f)
    return out


# viewer data tied to the floors of the build it was made on
FLOOR_BOUND = ("furniture", "furniture_unplaced", "markers", "comments")


def validate_view(v: dict, old: dict) -> dict:
    if not isinstance(v, dict):
        raise HTTPException(400, "Ожидается объект")
    out = dict(old)
    if "name" in v:
        out["name"] = _s(v["name"], "name", 120)
    if "site" in v:
        st = v["site"]
        if st is None:
            out.pop("site", None)
        else:
            if not isinstance(st, dict):
                raise HTTPException(400, "view.site: ожидается объект")
            out["site"] = {"lat": _f(st.get("lat"), -85, 85, "site.lat"), "lon": _f(st.get("lon"), -180, 180, "site.lon"),
                           "azimuth": _f(st.get("azimuth", 0), -360, 360, "site.azimuth"),
                           "scale": _f(st.get("scale", 1), 0.01, 100, "site.scale")}
            if st.get("tiles"):
                t = _s(st["tiles"], "site.tiles", 300)
                if not t.startswith("https://") or not all(k in t for k in ("{z}", "{x}", "{y}")):
                    raise HTTPException(400, "view.site.tiles: шаблон https://…/{z}/{x}/{y}.png")
                out["site"]["tiles"] = t
                out["site"]["attribution"] = _s(st.get("attribution", ""), "site.attribution", 200)
    if "detail" in v:
        dt = v["detail"] or {}
        if not isinstance(dt, dict):
            raise HTTPException(400, "view.detail: ожидается объект")
        cur = dict(old.get("detail") or {})
        if "offset" in dt:
            if not isinstance(dt["offset"], list) or len(dt["offset"]) != 3:
                raise HTTPException(400, "view.detail.offset: ожидается [x, y, z]")
            cur["offset"] = [_f(c, -1e4, 1e4, "detail.offset") for c in dt["offset"]]
        if "rotation" in dt:
            cur["rotation"] = _f(dt["rotation"], -360, 360, "detail.rotation")
        if "scale" in dt:
            cur["scale"] = _f(dt["scale"], 1e-4, 1e4, "detail.scale")
        out["detail"] = cur
    for k in ("comments", "markers"):
        if k in v:
            out[k] = _pins(v[k], k)
    if "furniture" in v:
        out["furniture"] = _furniture(v["furniture"])
    if "furniture_unplaced" in v:
        # only removal (after the items were put back on a floor or deleted): ids to keep
        keep = v["furniture_unplaced"]
        if not isinstance(keep, list):
            raise HTTPException(400, "view.furniture_unplaced: ожидается список")
        ids = {it.get("id") if isinstance(it, dict) else it for it in keep}
        rest = [u for u in old.get("furniture_unplaced") or [] if u.get("id") in ids]
        if rest:
            out["furniture_unplaced"] = rest
        else:
            out.pop("furniture_unplaced", None)
    return out


@app.get("/api/jobs/{jid}/view")
def get_view(jid: str):
    with db.session() as s:
        return store.view_of(_project(s, jid))


@app.put("/api/jobs/{jid}/view")
def put_view(jid: str, v: dict):
    """Merge viewer settings: top-level keys given replace the stored ones."""
    with db.session() as s:
        p = _project(s, jid, lock=True)          # read-modify-write: one writer per project
        if any(k in v for k in FLOOR_BOUND):
            # these refer to floors of a particular build: never write them across a rebuild
            if store.has_active(s, jid):
                raise HTTPException(409, "Идёт перестроение модели: расстановка и метки сохранятся после него")
            if "_build" in v and v["_build"] != p.current_build:
                raise HTTPException(409, "Модель была перестроена: обновите страницу, чтобы не потерять изменения")
        view = validate_view(v, store.view_of(p))
        store.set_view(p, view)
    return view


@app.post("/api/jobs/{jid}/detail")
async def upload_detail(jid: str, file: UploadFile = File(...)):
    """Detailed model (GLB: facade, furniture...) shown over the generated one."""
    with db.session() as s:
        _project(s, jid)
    jdir = store.project_dir(jid)
    tmp = jdir / f"detail.glb.{uuid.uuid4().hex[:8]}.part"
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
    tmp.replace(jdir / "detail.glb")
    with db.session() as s:
        p = _project(s, jid, lock=True)
        d = dict(p.detail or {})
        d.update(file=Path(file.filename or "detail.glb").name[:200], size=size,
                 version=int(d.get("version", 0)) + 1)
        d.setdefault("offset", [0.0, 0.0, 0.0])
        d.setdefault("rotation", 0.0)
        d.setdefault("scale", 1.0)
        p.detail = d
        p.updated_at = func.now()
        return store.view_of(p)


@app.delete("/api/jobs/{jid}/detail")
def delete_detail(jid: str):
    with db.session() as s:
        p = _project(s, jid, lock=True)
        (store.project_dir(jid) / "detail.glb").unlink(missing_ok=True)
        p.detail = None
        p.updated_at = func.now()
        return store.view_of(p)


@app.get("/api/jobs/{jid}/detail.glb")
def get_detail(jid: str):
    with db.session() as s:
        _project(s, jid)
    p = store.project_dir(jid) / "detail.glb"
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="model/gltf-binary")


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    with db.session() as s:
        return store.public(s, _project(s, jid))


@app.post("/api/jobs/{jid}/rebuild")
def rebuild(jid: str, override: dict):
    if not isinstance(override, dict):
        raise HTTPException(400, "Ожидается объект")
    with db.session() as s:
        p = _project(s, jid, lock=True)          # check + enqueue under the row lock: no double builds
        if store.has_active(s, jid):
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


@app.get("/api/jobs/{jid}/drawing.{fmt}")
def export_drawing(jid: str, fmt: str):
    """Source drawing with the 2D-editor corrections applied (DXF or DWG)."""
    from .dxf_writer import dxf_to_dwg, export_edited_dxf, has_edits

    if fmt not in ("dxf", "dwg"):
        raise HTTPException(400, "Формат: dxf или dwg")
    with db.session() as s:
        p = _project(s, jid)
        cfg, input_path, filename = p.config or {}, p.input_path, p.filename
    if not has_edits(cfg):
        raise HTTPException(400, "Правок нет — сохранять нечего")
    jdir = store.project_dir(jid)
    src = jdir / input_path
    if src.suffix.lower() == ".dwg":
        src = jdir / "out" / (src.stem + ".dxf")
        if not src.exists():
            raise HTTPException(409, "Чертёж ещё не обработан")
    stem = Path(filename).stem + "_правки"
    # cache per configuration (edits, layer mapping, floors) actually applied
    key = hashlib.sha1(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    cache = jdir / "export" / key
    cache.mkdir(parents=True, exist_ok=True)
    dxf = cache / "edited.dxf"
    try:
        if not dxf.exists():
            export_edited_dxf(src, dxf, cfg)
        if fmt == "dxf":
            return FileResponse(dxf, media_type="image/vnd.dxf", filename=f"{stem}.dxf")
        dwg = cache / "edited.dwg"
        failed = cache / "edited.dwg.error"
        if not dwg.exists():
            if failed.exists():               # don't re-run a slow converter that already failed
                raise HTTPException(500, failed.read_text(encoding="utf-8"))
            try:
                dxf_to_dwg(dxf, dwg)
            except Exception as ex:
                failed.write_text(str(ex), encoding="utf-8")
                raise
        return FileResponse(dwg, media_type="application/acad", filename=f"{stem}.dwg")
    except HTTPException:
        raise
    except Exception as ex:
        log.exception("drawing export failed")
        raise HTTPException(500, str(ex))


@app.get("/api/jobs/{jid}/files/{path:path}")
def get_file(jid: str, path: str):
    with db.session() as s:
        p = _project(s, jid)
        filename = p.filename
        busy = store.has_active(s, jid)
    base = (store.project_dir(jid) / "out").resolve()
    f = (base / path).resolve()
    media = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png",
             ".ifc": "application/x-step", ".zip": "application/zip"}
    ext = f.suffix.lower()
    if base in f.parents and f.parent == base / "debug" and ext == ".png" and not f.is_file() and not busy:
        render_debug(base, f.name)              # rendered on demand from the cached plans
    if base not in f.parents or not f.is_file() or ext not in media:
        raise HTTPException(404)
    if ext in (".ifc", ".zip"):
        stem = Path(filename).stem
        return FileResponse(f, media_type=media[ext], filename=f"{stem}{'_obj.zip' if ext == '.zip' else ext}")
    return FileResponse(f, media_type=media[ext])


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
