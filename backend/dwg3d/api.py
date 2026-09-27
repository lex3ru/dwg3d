"""HTTP API: upload DWG/DXF -> background processing -> glTF + metadata.

  POST /api/jobs                 multipart: file, config (optional JSON string)
  GET  /api/jobs/{id}            status / progress / result
  POST /api/jobs/{id}/rebuild    JSON config override (floors.items, layers...)
  GET  /api/jobs/{id}/files/...  model.glb, metadata.json, debug/*.png
  GET  /api/config/default       default config
  GET  /api/health               converter availability

Run:  uvicorn dwg3d.api:app --port 8765
"""
from __future__ import annotations

import json
import logging
import os
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

from .config import deep_merge, load_config
from .convert import available_converters
from .pipeline import run

log = logging.getLogger("dwg3d.api")
ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("DWG3D_DATA", ROOT / "data")) / "jobs"
DATA.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = int(os.environ.get("DWG3D_MAX_UPLOAD_MB", "200")) * 1024 * 1024

app = FastAPI(title="dwg3d")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_executor = ThreadPoolExecutor(max_workers=int(os.environ.get("DWG3D_WORKERS", "2")))
_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _job_dir(jid: str) -> Path:
    return DATA / jid


def _save(job: dict):
    (_job_dir(job["id"]) / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def _update(jid: str, **kw):
    with _lock:
        job = _jobs[jid]
        job.update(kw, updated=time.time())
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


_load_existing()


def _public(job: dict) -> dict:
    out = {k: v for k, v in job.items() if k not in ("input",)}
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
        _update(jid, status="running", stage=stage, progress=round(frac, 3), message=msg)

    try:
        _update(jid, status="running", stage="start", progress=0.0, message="Запуск", error=None)
        meta = run(src, jdir / "out", job.get("config") or {}, progress=progress)
        meta.pop("config", None)
        if src.suffix.lower() == ".dxf" and job["input"].lower().endswith(".dwg"):
            meta["converter"] = job.get("result", {}).get("converter", meta.get("converter"))
        result = {k: meta[k] for k in ("source", "units", "units_source", "converter", "floors", "roof_node",
                                        "height_range", "candidates", "triangles", "warnings", "elapsed_s",
                                        "center", "exports", "extent")}
        result["layers"] = meta["layers"]
        _update(jid, status="done", stage="done", progress=1.0, message="Готово", result=result,
                build=job.get("build", 0) + 1)
    except Exception as ex:
        log.exception("job %s failed", jid)
        _update(jid, status="error", stage="error", error=str(ex), trace=traceback.format_exc()[-3000:])


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
    jid = uuid.uuid4().hex[:12]
    jdir = _job_dir(jid)
    jdir.mkdir(parents=True)
    size = 0
    with open(jdir / f"input{ext}", "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
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


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    return _public(_jobs[jid])


@app.post("/api/jobs/{jid}/rebuild")
def rebuild(jid: str, override: dict):
    if jid not in _jobs:
        raise HTTPException(404, "Задача не найдена")
    job = _jobs[jid]
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "Задача ещё выполняется")
    # floors.items is replaced wholesale (a full assignment list), the rest is merged
    cfg = deep_merge(job.get("config") or {}, override or {})
    _update(jid, status="queued", stage="queued", progress=0.0, message="В очереди", config=cfg)
    _executor.submit(_process, jid)
    return _public(_jobs[jid])


@app.get("/api/jobs/{jid}/files/{path:path}")
def get_file(jid: str, path: str):
    if jid not in _jobs:
        raise HTTPException(404)
    base = (_job_dir(jid) / "out").resolve()
    p = (base / path).resolve()
    media = {".glb": "model/gltf-binary", ".json": "application/json", ".png": "image/png",
             ".ifc": "application/x-step", ".zip": "application/zip"}
    ext = p.suffix.lower()
    if base not in p.parents or not p.is_file() or ext not in media:
        raise HTTPException(404)
    if ext in (".ifc", ".zip"):
        stem = Path(_jobs[jid]["filename"]).stem
        return FileResponse(p, media_type=media[ext], filename=f"{stem}{'_obj.zip' if ext == '.zip' else ext}")
    return FileResponse(p, media_type=media[ext])


_dist = ROOT / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
