"""HTTP API: upload DWG/DXF -> background processing -> glTF + metadata.

  POST /api/jobs                 multipart: file, config (optional JSON string)
  GET  /api/jobs                 processed jobs (building switcher)
  GET  /api/jobs/{id}            status / progress / result
  GET/PUT /api/jobs/{id}/view    viewer settings: map binding, detail model
                                 alignment, markers, comments, furniture
                                 (no rebuild)
  POST/DELETE /api/jobs/{id}/detail, GET /api/jobs/{id}/detail.glb
                                 detailed model (GLB) shown over the generated one
  POST /api/jobs/{id}/rebuild    JSON config override (floors.items, layers...)
  GET  /api/jobs/{id}/files/...  model.glb, metadata.json, debug/*.png
  GET  /api/config/default       default config
  GET  /api/health               converter availability

Run:  uvicorn dwg3d.api:app --port 8765

Environment:
  DWG3D_DATA              data directory (default <project>/data)
  DWG3D_MAX_UPLOAD_MB     upload limit (200)
  DWG3D_WORKERS           parallel builds (2)
  DWG3D_CORS_ORIGINS      comma-separated origins allowed cross-origin (none;
                          the built UI and the Vite dev proxy are same-origin)
  DWG3D_RETENTION_DAYS    delete jobs not touched for N days (0 = keep forever)

There is no authentication: bind to 127.0.0.1 or put it behind a reverse
proxy that authenticates. Job state lives in this process, so run a single
uvicorn worker.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ConfigError, deep_merge, load_config, validate_config
from .convert import available_converters
from .edits import anchor_of, remap_view
from .pipeline import render_debug, run

log = logging.getLogger("dwg3d.api")
ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DWG3D_DATA", ROOT / "data")) / "jobs"
DATA.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = int(os.environ.get("DWG3D_MAX_UPLOAD_MB", "200")) * 1024 * 1024
RETENTION_DAYS = float(os.environ.get("DWG3D_RETENTION_DAYS", "0"))
# fields kept in job.json for diagnostics but never sent to the client
PRIVATE = ("input", "trace")

app = FastAPI(title="dwg3d")
if origins := [o.strip() for o in os.environ.get("DWG3D_CORS_ORIGINS", "").split(",") if o.strip()]:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"])

_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("DWG3D_WORKERS", "2")))
_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_last_cleanup = 0.0


def _job_dir(jid: str) -> Path:
    return DATA / jid


def _save(job: dict):
    (_job_dir(job["id"]) / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def _update(jid: str, persist: bool = True, **kw):
    with _lock:
        job = _jobs[jid]
        job.update(kw, updated=time.time())
        if persist:
            _save(job)


def _load_existing():
    for p in DATA.glob("*/job.json"):
        try:
            job = json.loads(p.read_text(encoding="utf-8"))
            if job.get("status") not in ("done", "error"):
                job.update(status="error", error="Сервер был перезапущен во время обработки")
            _jobs[job["id"]] = job
        except Exception:
            pass


def _cleanup():
    """Delete finished jobs untouched for RETENTION_DAYS (disabled when 0)."""
    global _last_cleanup
    if RETENTION_DAYS <= 0 or time.time() - _last_cleanup < 3600:
        return
    _last_cleanup = time.time()
    cutoff = time.time() - RETENTION_DAYS * 86400
    with _lock:
        old = [j["id"] for j in _jobs.values()
               if j.get("status") in ("done", "error") and j.get("updated", 0) < cutoff]
        for jid in old:
            _jobs.pop(jid, None)
    for jid in old:
        shutil.rmtree(_job_dir(jid), ignore_errors=True)
        log.info("job %s removed (retention %s days)", jid, RETENTION_DAYS)


_load_existing()
_cleanup()


def _public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if k not in PRIVATE}
    if job.get("status") == "done":
        v = job.get("build", 0)
        out["model_url"] = f"/api/jobs/{job['id']}/files/model.glb?v={v}"
        out["metadata_url"] = f"/api/jobs/{job['id']}/files/metadata.json?v={v}"
    return out


def _process(jid: str):
    job = _jobs[jid]
    jdir = _job_dir(jid)
    src = jdir / job["input"]
    # reuse the converted DXF on rebuilds (conversion is the slow external step)
    dxf = jdir / "out" / (src.stem + ".dxf")
    if src.suffix.lower() == ".dwg" and dxf.exists():
        src = dxf

    def progress(stage, frac, msg=""):
        # job.json is rewritten only when the stage changes, not on every tick
        _update(jid, persist=stage != job.get("stage"), status="running", stage=stage,
                progress=round(frac, 3), message=msg)

    try:
        _update(jid, status="running", stage="start", progress=0.0, message="Запуск", error=None)
        meta = run(src, jdir / "out", job.get("config") or {}, progress=progress, debug_png=False)
        cfg_used = meta.pop("config", None) or {}
        if src.suffix.lower() == ".dxf" and job["input"].lower().endswith(".dwg"):
            meta["converter"] = job.get("result", {}).get("converter", meta.get("converter"))
        result = {k: meta[k] for k in ("source", "units", "units_source", "converter", "floors", "roof_node",
                                        "height_range", "candidates", "triangles", "warnings", "elapsed_s",
                                        "center", "exports", "extent", "quality", "edits_unmatched",
                                        "entrances", "pois", "room_types")}
        result["layers"] = meta["layers"]
        # persist the corrections re-anchored to the floors of this build
        cfg = dict(job.get("config") or {})
        cfg["edits"] = cfg_used.get("edits") or {}
        if cfg_used.get("edits_unmatched"):
            cfg["edits_unmatched"] = cfg_used["edits_unmatched"]
        else:
            cfg.pop("edits_unmatched", None)
        if (cfg.get("floors") or {}).get("items"):
            cfg["floors"] = {**cfg["floors"], "items": cfg_used["floors"]["items"]}
        with _lock:
            # furniture and pins follow their floors into the new build (ids / alignment may change)
            view, warns = remap_view(job.get("view"), job.get("result"), result)
            result["warnings"] = list(result.get("warnings") or []) + warns
            _update(jid, status="done", stage="done", progress=1.0, message="Готово", result=result,
                    config=cfg, build=job.get("build", 0) + 1, view=view)
    except Exception as ex:
        log.exception("job %s failed", jid)
        msg = str(ex) if isinstance(ex, (RuntimeError, ValueError, OSError)) else f"{type(ex).__name__}: {ex}"
        _update(jid, status="error", stage="error", error=msg[:1000], trace=traceback.format_exc()[-3000:])


@app.get("/api/health")
def health():
    return {"ok": True, "converters": available_converters()}


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
    jdir = _job_dir(jid)
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
    job = {"id": jid, "filename": name, "input": f"input{ext}", "size": size, "status": "queued",
           "stage": "queued", "progress": 0.0, "message": "В очереди", "config": override,
           "created": time.time(), "updated": time.time(), "build": 0}
    with _lock:
        _jobs[jid] = job
        _save(job)
    _executor.submit(_process, jid)
    return _public(job)


@app.get("/api/jobs")
def list_jobs():
    """Processed buildings (for the building switcher), newest first."""
    with _lock:
        jobs = list(_jobs.values())
    out = []
    for j in sorted(jobs, key=lambda j: -j.get("updated", 0)):
        res = j.get("result") or {}
        out.append({"id": j["id"], "filename": j.get("filename"), "status": j.get("status"),
                    "updated": j.get("updated"), "floors": len(res.get("floors") or []),
                    "name": ((j.get("view") or {}).get("name")) or Path(j.get("filename") or "").stem})
    return out


# ------------------------------------------------------ viewer settings ---
# Per-job viewer state that needs no rebuild: map binding, detail-model
# alignment, user markers and comments, placed furniture. Stored in job.json ("view").
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
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    return _jobs[jid].get("view") or {}


@app.put("/api/jobs/{jid}/view")
def put_view(jid: str, v: dict):
    """Merge viewer settings: top-level keys given replace the stored ones."""
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    with _lock:
        job = _jobs[jid]
        if any(k in v for k in FLOOR_BOUND):
            # these refer to floors of a particular build: never write them across a rebuild
            if job.get("status") in ("queued", "running"):
                raise HTTPException(409, "Идёт перестроение модели: расстановка и метки сохранятся после него")
            if "_build" in v and v["_build"] != job.get("build"):
                raise HTTPException(409, "Модель была перестроена: обновите страницу, чтобы не потерять изменения")
        view = validate_view(v, job.get("view") or {})
        _update(jid, view=view)
    return view


@app.post("/api/jobs/{jid}/detail")
async def upload_detail(jid: str, file: UploadFile = File(...)):
    """Detailed model (GLB: facade, furniture...) shown over the generated one."""
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    jdir = _job_dir(jid)
    tmp = jdir / "detail.glb.part"
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
    with _lock:
        view = dict(_jobs[jid].get("view") or {})
        d = dict(view.get("detail") or {})
        d.update(file=Path(file.filename or "detail.glb").name[:200], size=size,
                 version=int(d.get("version", 0)) + 1)
        d.setdefault("offset", [0.0, 0.0, 0.0])
        d.setdefault("rotation", 0.0)
        d.setdefault("scale", 1.0)
        view["detail"] = d
        _update(jid, view=view)
    return view


@app.delete("/api/jobs/{jid}/detail")
def delete_detail(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    (_job_dir(jid) / "detail.glb").unlink(missing_ok=True)
    with _lock:
        view = dict(_jobs[jid].get("view") or {})
        view.pop("detail", None)
        _update(jid, view=view)
    return view


@app.get("/api/jobs/{jid}/detail.glb")
def get_detail(jid: str):
    p = _job_dir(jid) / "detail.glb"
    if jid not in _jobs or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="model/gltf-binary")


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    return _public(_jobs[jid])


@app.post("/api/jobs/{jid}/rebuild")
def rebuild(jid: str, override: dict):
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    if not isinstance(override, dict):
        raise HTTPException(400, "Ожидается объект")
    with _lock:                         # check + enqueue atomically: no double builds
        job = _jobs[jid]
        if job["status"] in ("queued", "running"):
            raise HTTPException(409, "Задача ещё выполняется")
        override = _anchor_override(job, override)
        # floors.items is replaced wholesale (a full assignment list), the rest is merged
        cfg = deep_merge(job.get("config") or {}, override)
        try:
            validate_config(load_config(cfg))
        except ConfigError as ex:
            raise HTTPException(400, str(ex))
        _update(jid, status="queued", stage="queued", progress=0.0, message="В очереди", config=cfg)
    _executor.submit(_process, jid)
    return _public(_jobs[jid])


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

    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    if fmt not in ("dxf", "dwg"):
        raise HTTPException(400, "Формат: dxf или dwg")
    job = _jobs[jid]
    cfg = job.get("config") or {}
    if not has_edits(cfg):
        raise HTTPException(400, "Правок нет — сохранять нечего")
    jdir = _job_dir(jid)
    src = jdir / job["input"]
    if src.suffix.lower() == ".dwg":
        src = jdir / "out" / (src.stem + ".dxf")
        if not src.exists():
            raise HTTPException(409, "Чертёж ещё не обработан")
    stem = Path(job["filename"]).stem + "_правки"
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
    if jid not in _jobs:
        raise HTTPException(404)
    base = (_job_dir(jid) / "out").resolve()
    p = (base / path).resolve()
    media = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png",
             ".ifc": "application/x-step", ".zip": "application/zip"}
    ext = p.suffix.lower()
    if base in p.parents and p.parent == base / "debug" and ext == ".png" and not p.is_file():
        with _lock:
            busy = _jobs[jid].get("status") in ("queued", "running")
        if not busy:
            render_debug(base, p.name)          # rendered on demand from the cached plans
    if base not in p.parents or not p.is_file() or ext not in media:
        raise HTTPException(404)
    if ext in (".ifc", ".zip"):
        stem = Path(_jobs[jid]["filename"]).stem
        return FileResponse(p, media_type=media[ext], filename=f"{stem}{'_obj.zip' if ext == '.zip' else ext}")
    return FileResponse(p, media_type=media[ext])


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
