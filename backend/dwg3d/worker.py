"""Build workers: take queued jobs from PostgreSQL and run the pipeline.

A job is claimed with SELECT ... FOR UPDATE SKIP LOCKED, so any number of
threads and processes (API processes, `python -m dwg3d worker`) can share the
queue. Running jobs send a heartbeat; a job whose process died is marked
failed by whichever worker notices it first.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
import traceback

from sqlalchemy import func, select, text, update

from . import db, store
from .models import Build, Job
from .pipeline import run

log = logging.getLogger("dwg3d.worker")
POLL_S = 1.0
HEARTBEAT_S = 15
STALE_S = 120
RESULT_KEYS = ("source", "units", "units_source", "converter", "floors", "roof_node", "height_range",
               "candidates", "triangles", "warnings", "elapsed_s", "center", "exports", "extent", "quality",
               "edits_unmatched", "entrances", "pois", "room_types", "layers")

_wake = threading.Event()
_running: set[int] = set()
_running_lock = threading.Lock()
_started = False
_start_lock = threading.Lock()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def wake():
    """A job was queued by this process: don't wait for the next poll."""
    _wake.set()


def claim() -> tuple[int, str] | None:
    with db.session() as s:
        row = s.execute(text("""
            UPDATE jobs SET status = 'running', stage = 'start', progress = 0, message = 'Запуск',
                   error = NULL, worker = :w, started_at = now(), heartbeat_at = now()
            WHERE id = (SELECT id FROM jobs WHERE status = 'queued' ORDER BY id
                        FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING id, project_id"""), {"w": WORKER_ID}).first()
    return (row[0], row[1]) if row else None


def _set(jid: int, **kw):
    with db.session() as s:
        s.execute(update(Job).where(Job.id == jid).values(**kw, heartbeat_at=func.now()))


def process(jid: int, pid: str):
    with db.session() as s:
        p = store.get_project(s, pid)
        if p is None:
            s.execute(update(Job).where(Job.id == jid).values(status="error", stage="error",
                                                              error="Проект удалён", finished_at=func.now()))
            return
        cfg_in, input_path = dict(p.config or {}), p.input_path
        old = store.current_build(s, p)
        old_converter = (old.result or {}).get("converter") if old else None
    pdir = store.project_dir(pid)
    src = pdir / input_path
    # reuse the converted DXF on rebuilds (conversion is the slow external step)
    dxf = pdir / "out" / (src.stem + ".dxf")
    if src.suffix.lower() == ".dwg" and dxf.exists():
        src = dxf
    last = {"stage": "start", "t": 0.0}

    def progress(stage, frac, msg=""):
        # the row is written when the stage changes and at most twice a second
        now = time.monotonic()
        if stage != last["stage"] or now - last["t"] >= 0.5:
            last.update(stage=stage, t=now)
            _set(jid, stage=stage, progress=round(frac, 3), message=msg)

    try:
        meta = run(src, pdir / "out", cfg_in, progress=progress, debug_png=False)
        cfg_used = meta.pop("config", None) or {}
        if src.suffix.lower() == ".dxf" and input_path.lower().endswith(".dwg"):
            meta["converter"] = old_converter or meta.get("converter")
        result = {k: meta[k] for k in RESULT_KEYS}
        # persist the corrections re-anchored to the floors of this build
        cfg = dict(cfg_in)
        cfg["edits"] = cfg_used.get("edits") or {}
        if cfg_used.get("edits_unmatched"):
            cfg["edits_unmatched"] = cfg_used["edits_unmatched"]
        else:
            cfg.pop("edits_unmatched", None)
        if (cfg.get("floors") or {}).get("items"):
            cfg["floors"] = {**cfg["floors"], "items": cfg_used["floors"]["items"]}
        with db.session() as s:
            p = store.get_project(s, pid, lock=True)
            if p is None:
                raise RuntimeError("Проект удалён во время обработки")
            old = store.current_build(s, p)
            # floors keep their rows; furniture and pins move with them (ids / alignment may change)
            warns = store.sync_floors(s, pid, result, old.result if old else None)
            result["warnings"] = list(result.get("warnings") or []) + warns
            n = p.current_build + 1
            s.add(Build(project_id=pid, n=n, result=result, config=cfg, out_dir="out"))
            s.flush()
            p.current_build = n
            p.config = cfg
            p.updated_at = func.now()
            s.execute(update(Job).where(Job.id == jid).values(
                status="done", stage="done", progress=1.0, message="Готово", finished_at=func.now()))
    except Exception as ex:
        log.exception("job %s (%s) failed", jid, pid)
        msg = str(ex) if isinstance(ex, (RuntimeError, ValueError, OSError)) else f"{type(ex).__name__}: {ex}"
        _set(jid, status="error", stage="error", error=msg[:1000], trace=traceback.format_exc()[-3000:],
             finished_at=func.now())


def _loop():
    last_reap = 0.0
    while True:
        try:
            if time.monotonic() - last_reap > HEARTBEAT_S:
                last_reap = time.monotonic()
                with db.session() as s:
                    if n := store.fail_stale_jobs(s, STALE_S):
                        log.warning("%d job(s) marked failed: no heartbeat for %d s", n, STALE_S)
            job = claim()
        except Exception:
            log.exception("job queue unavailable")
            time.sleep(5)
            continue
        if job is None:
            _wake.wait(POLL_S)
            _wake.clear()
            continue
        with _running_lock:
            _running.add(job[0])
        try:
            process(*job)
        finally:
            with _running_lock:
                _running.discard(job[0])


def _heartbeat():
    while True:
        time.sleep(HEARTBEAT_S)
        with _running_lock:
            ids = list(_running)
        if not ids:
            continue
        try:
            with db.session() as s:
                s.execute(update(Job).where(Job.id.in_(ids), Job.status == "running").values(heartbeat_at=func.now()))
        except Exception:
            log.exception("heartbeat failed")


def start(n: int):
    """Start `n` worker threads in this process (once)."""
    global _started
    with _start_lock:
        if _started or n <= 0:
            return
        _started = True
    threading.Thread(target=_heartbeat, name="dwg3d-heartbeat", daemon=True).start()
    for i in range(n):
        threading.Thread(target=_loop, name=f"dwg3d-worker-{i}", daemon=True).start()
    log.info("%d build worker(s) started (%s)", n, WORKER_ID)


def serve(n: int):
    """`python -m dwg3d worker`: a process that only builds."""
    db.migrate()
    start(n)
    while True:
        time.sleep(3600)


def queue_stats() -> dict:
    with db.session() as s:
        rows = s.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    return dict(rows)

