"""Build workers: take queued jobs from PostgreSQL and run the pipeline.

A job is claimed with SELECT ... FOR UPDATE SKIP LOCKED, so any number of
threads and processes (API processes, `python -m dwg3d worker`) can share the
queue. Running jobs send a heartbeat; a job whose process died is marked
failed by whichever worker notices it first.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import traceback
from contextlib import contextmanager

from sqlalchemy import func, select, text, update

from . import db, files, rooms, store
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
# held while claiming; `paused()` holds it to keep this process's workers off the queue
_gate = threading.Lock()
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
            RETURNING id, drawing_id"""), {"w": WORKER_ID}).first()
    return (row[0], row[1]) if row else None


def _set(jid: int, **kw):
    with db.session() as s:
        s.execute(update(Job).where(Job.id == jid).values(**kw, heartbeat_at=func.now()))


def process(jid: int, did: str):
    with db.session() as s:
        d = store.get_drawing(s, did)
        if d is None:
            s.execute(update(Job).where(Job.id == jid).values(status="error", stage="error",
                                                              error="Чертёж удалён", finished_at=func.now()))
            return
        cfg_in, input_path = dict(d.config or {}), d.input_path
        old = store.current_build(s, d)
        old_converter = (old.result or {}).get("converter") if old else None
        old_dir = old.out_dir if old else None
    with files.lock(did):
        _build(jid, did, cfg_in, input_path, old_converter, old_dir)


def _build(jid: int, did: str, cfg_in: dict, input_path: str, old_converter: str | None, old_dir: str | None):
    st = files.store()
    last = {"stage": "start", "t": 0.0}

    def progress(stage, frac, msg=""):
        # the row is written when the stage changes and at most twice a second
        now = time.monotonic()
        if stage != last["stage"] or now - last["t"] >= 0.5:
            last.update(stage=stage, t=now)
            _set(jid, stage=stage, progress=round(frac, 3), message=msg)

    try:
        # the working copy: the input and the previous build as out/ (converted DXF, plan caches)
        ddir = st.pull(did, paths=[input_path], trees=[(old_dir, "out")] if old_dir else [])
        src = ddir / input_path
        if not src.is_file():
            raise RuntimeError("Исходный файл чертежа не найден в хранилище")
        # reuse the converted DXF on rebuilds (conversion is the slow external step)
        dxf = ddir / "out" / (src.stem + ".dxf")
        if src.suffix.lower() == ".dwg" and dxf.exists():
            src = dxf
        meta = run(src, ddir / "out", cfg_in, progress=progress, debug_png=False)
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
        _set(jid, stage="export", progress=0.99, message="Сохранение файлов")
        # the files first, as a tree of their own: the build becomes current below,
        # until then readers keep getting the files of the current one
        out_dir = f"builds/{jid}"
        st.push(did, "out", to=out_dir, base=old_dir)
        with db.session() as s:
            d = store.get_drawing(s, did, lock=True)
            if d is None:
                raise RuntimeError("Чертёж удалён во время обработки")
            old = store.current_build(s, d)
            # floors keep their rows; layer objects and pins move with them (ids / alignment may change)
            moves: dict = {}
            warns = store.sync_floors(s, did, result, old.result if old else None, moves)
            result["warnings"] = list(result.get("warnings") or []) + warns
            # rooms keep their ids too; objects learn which room they stand in
            rooms.sync(s, did, result, _plans(ddir / "out", result), moves)
            rooms.relocate(s, did)
            n = d.current_build + 1
            s.add(Build(drawing_id=did, n=n, result=result, config=cfg, out_dir=out_dir))
            s.flush()
            d.current_build = n
            d.config = cfg
            d.updated_at = func.now()
            s.execute(update(Job).where(Job.id == jid).values(
                status="done", stage="done", progress=1.0, message="Готово", finished_at=func.now()))
    except Exception as ex:
        log.exception("job %s (%s) failed", jid, did)
        msg = str(ex) if isinstance(ex, (RuntimeError, ValueError, OSError)) else f"{type(ex).__name__}: {ex}"
        _set(jid, status="error", stage="error", error=msg[:1000], trace=traceback.format_exc()[-3000:],
             finished_at=func.now())
        return
    # the trees of older builds and of builds that failed to commit; the previous
    # build's stays for a while, for readers that looked it up just before the switch
    try:
        files.prune(st, did, keep={out_dir, *([old_dir] if old_dir else [])})
    except Exception:
        log.exception("old build files of %s not removed", did)


def _plans(out, result: dict) -> dict[str, dict]:
    """The plan JSON of each floor of a build (rooms with outlines), by floor id."""
    plans = {}
    for f in result.get("floors") or []:
        p = out / (f.get("plan") or "")
        if f.get("plan") and p.is_file():
            plans[f["id"]] = json.loads(p.read_text(encoding="utf-8"))
    return plans


def _loop():
    last_reap = 0.0
    while True:
        try:
            if time.monotonic() - last_reap > HEARTBEAT_S:
                last_reap = time.monotonic()
                with db.session() as s:
                    if n := store.fail_stale_jobs(s, STALE_S):
                        log.warning("%d job(s) marked failed: no heartbeat for %d s", n, STALE_S)
            with _gate:
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


@contextmanager
def paused():
    """Keep this process's worker threads from taking jobs (tests drive the queue by hand)."""
    with _gate:
        yield


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

