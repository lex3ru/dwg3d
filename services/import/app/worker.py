"""The build worker: takes queued builds and runs the drawing pipeline.

    python -m app.worker

A build is claimed with FOR UPDATE SKIP LOCKED, so any number of workers can
share the queue. A running build sends a heartbeat; one whose worker died is
marked failed by whichever worker notices it first. The API process never
builds.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import time
import traceback
from pathlib import Path

from sqlalchemy import func, select, text, update
from twin_chassis import Database, Settings, events, log
from twin_chassis.bus import Bus

from . import storage, store
from .dwg.pipeline import run as run_pipeline
from .models import builds, drawing_files, drawings

logger = logging.getLogger("twin.import.worker")
POLL_S = 1.0
HEARTBEAT_S = 15
STALE_S = 120


class Gone(Exception):
    """The drawing was deleted while its build waited or ran."""


class Worker:
    def __init__(self, db: Database, bus: Bus):
        self.db, self.bus = db, bus
        self.id = f"{socket.gethostname()}:{os.getpid()}"
        self._last_reap = 0.0

    # --------------------------------------------------------------- queue ---
    async def claim(self):
        async with self.db.begin() as session:
            return (await session.execute(text("""
                UPDATE builds SET status = 'running', stage = 'start', progress = 0, message = 'Запуск',
                       error = NULL, worker = :w, started_at = now(), heartbeat_at = now()
                WHERE id = (SELECT id FROM builds WHERE status = 'queued' ORDER BY created_at, id
                            FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING id"""), {"w": self.id})).scalar_one_or_none()

    async def reap(self, stale_s: float = STALE_S) -> int:
        """Builds whose worker stopped reporting: failed, with an event, so nobody waits forever."""
        async with self.db.begin() as session:
            rows = (await session.execute(
                select(builds, drawings.c.building_id).join(drawings, drawings.c.id == builds.c.drawing_id)
                .where(builds.c.status == "running",
                       builds.c.heartbeat_at < func.now() - text(f"interval '{int(stale_s)} seconds'"))
                .with_for_update(of=builds, skip_locked=True))).all()
            for row in rows:
                message = "Сборка прервана: обработчик перестал отвечать. Запустите её ещё раз."
                await session.execute(update(builds).where(builds.c.id == row.id).values(
                    status="error", stage="error", error=message, finished_at=func.now()))
                await store.emit_build(session, "failed", row, row.building_id, message=message)
        return len(rows)

    async def run_once(self) -> bool:
        """Take one build from the queue and finish it; False when the queue is empty."""
        build_id = await self.claim()
        if build_id is None:
            return False
        await self.process(build_id)
        return True

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("build worker started (%s)", self.id)
        while not stop.is_set():
            try:
                if time.monotonic() - self._last_reap > HEARTBEAT_S:
                    self._last_reap = time.monotonic()
                    if n := await self.reap():
                        logger.warning("%d build(s) marked failed: no heartbeat for %d s", n, STALE_S)
                if await self.run_once():
                    continue
            except Exception:
                logger.exception("the build queue is unavailable")
                await asyncio.sleep(5)
                continue
            try:
                await asyncio.wait_for(stop.wait(), POLL_S)
            except TimeoutError:
                pass

    # --------------------------------------------------------------- build ---
    async def process(self, build_id) -> None:
        async with self.db.begin() as session:
            b = (await session.execute(select(builds).where(builds.c.id == build_id))).one()
            d = (await session.execute(select(drawings).where(drawings.c.id == b.drawing_id))).one()
            f = (await session.execute(select(drawing_files).where(drawing_files.c.id == b.file_id))).one()
            if d.deleted_at is None:
                await store.emit_build(session, "started", b, d.building_id)
        loop = asyncio.get_running_loop()
        last = {"stage": "start", "at": 0.0}
        pending: set[asyncio.Task] = set()

        def progress(stage: str, fraction: float, message: str = "") -> None:     # called in the pipeline's thread
            now = time.monotonic()
            if stage != last["stage"] or now - last["at"] >= 0.5:                  # a stage change, else twice a second
                last.update(stage=stage, at=now)
                loop.call_soon_threadsafe(report, stage, round(fraction, 3), message)

        def report(stage: str, fraction: float, message: str) -> None:
            task = loop.create_task(self._progress(b, d.building_id, stage, fraction, message))
            pending.add(task)
            task.add_done_callback(pending.discard)

        heartbeat = asyncio.create_task(self._heartbeat(build_id))
        try:
            if d.deleted_at is not None:
                raise Gone
            meta, files = await asyncio.to_thread(self._build, b, d, f, progress)
            await asyncio.gather(*pending, return_exceptions=True)
            await self._finish(b, d, meta, files)
        except Gone:
            await self._fail(b, d, "Чертёж удалён", None, announce=False)
        except Exception as ex:
            logger.exception("build %s of drawing %s failed", b.id, b.drawing_id)
            known = isinstance(ex, RuntimeError | ValueError | OSError)
            message = str(ex) if known and str(ex) else f"{type(ex).__name__}: {ex}"
            await self._fail(b, d, message[:1000], traceback.format_exc()[-3000:])
        finally:
            heartbeat.cancel()

    def _build(self, b, d, f, progress) -> tuple[dict, list[str]]:
        """The pipeline on a working copy; returns its result and the files stored. Runs in a thread."""
        work = storage.workdir(d.id)
        tag = f.sha256[:16]
        for stale in work.iterdir():                 # working copies of earlier files of this drawing
            if stale.is_dir() and stale.name != tag and stale.name != "export":
                _rmtree(stale)
        source = work / tag / "input" / f.filename
        if not source.is_file() and not storage.bucket().download(f.storage_key, source):
            raise RuntimeError("Исходный файл чертежа не найден в хранилище")
        out = work / tag / "out"
        # the converted DXF is kept with the working copy: conversion is the slow external step
        dxf = out / (source.stem + ".dxf")
        is_dwg = source.suffix.lower() == ".dwg"
        previous = None
        if is_dwg and dxf.exists():
            previous = (out / "converter.txt").read_text().strip() if (out / "converter.txt").exists() else None
            source = dxf
        meta = run_pipeline(source, out, d.config or {}, progress=progress, debug_png=False)
        if is_dwg:
            if previous:
                meta["converter"] = previous
            else:
                (out / "converter.txt").write_text(str(meta.get("converter") or ""))
        files = storage.push_build(out, b.id, dxf.name if is_dwg else None)
        return meta, files

    async def _progress(self, b, building_id, stage: str, fraction: float, message: str) -> None:
        try:
            async with self.db.begin() as session:
                await session.execute(update(builds).where(builds.c.id == b.id, builds.c.status == "running").values(
                    stage=stage, progress=fraction, message=message, heartbeat_at=func.now()))
            await self.bus.announce(events.envelope(
                "import.build.progress", ("build", b.id),
                {"build_id": str(b.id), "drawing_id": str(b.drawing_id), "n": b.n, "stage": stage,
                 "progress": fraction, "message": message},
                actor={"kind": "service", "id": "import"}, building_id=building_id))
        except Exception:
            logger.exception("progress of build %s not reported", b.id)

    async def _heartbeat(self, build_id) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            try:
                async with self.db.begin() as session:
                    await session.execute(update(builds).where(builds.c.id == build_id, builds.c.status == "running")
                                          .values(heartbeat_at=func.now()))
            except Exception:
                logger.exception("heartbeat failed")

    async def _finish(self, b, d, meta: dict, files: list[str]) -> None:
        used = meta.pop("config", None) or {}
        result = {k: meta[k] for k in store.RESULT_KEYS if k in meta}
        result["files"] = files
        # the corrections re-anchored to the floors of this build are what the drawing keeps
        config = dict(d.config or {})
        config["edits"] = used.get("edits") or {}
        if used.get("edits_unmatched"):
            config["edits_unmatched"] = used["edits_unmatched"]
        else:
            config.pop("edits_unmatched", None)
        if (config.get("floors") or {}).get("items"):
            config["floors"] = {**config["floors"], "items": used["floors"]["items"]}
        async with self.db.begin() as session:
            current = await store.get_drawing(session, d.id, lock=True)
            if current is None:
                raise Gone
            await session.execute(update(builds).where(builds.c.id == b.id).values(
                status="done", stage="done", progress=1.0, message="Готово", result=result, config=config,
                out_prefix=storage.build_prefix(b.id), finished_at=func.now()))
            await session.execute(update(drawings).where(drawings.c.id == d.id).values(
                config=config, current_build_id=b.id, updated_at=func.now()))
            floors = result.get("floors") or []
            await store.emit_build(
                session, "finished", b, d.building_id, floors=len(floors),
                rooms=sum(len(f.get("rooms") or []) for f in floors), warnings=len(result.get("warnings") or []),
                quality=(result.get("quality") or {}).get("status", "ok"))

    async def _fail(self, b, d, message: str, trace: str | None, announce: bool = True) -> None:
        async with self.db.begin() as session:
            await session.execute(update(builds).where(builds.c.id == b.id).values(
                status="error", stage="error", error=message, trace=trace, finished_at=func.now()))
            if announce:
                await store.emit_build(session, "failed", b, d.building_id, message=message)


def _rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


async def main() -> None:
    settings = Settings.from_env("import")
    log.setup("import")
    events.configure("import", settings.contracts)
    db = Database(settings.database_url)
    bus = Bus("import", settings.nats_url, db, settings.bus_prefix)
    await bus.start()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await Worker(db, bus).run_forever(stop)
    finally:
        await bus.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
