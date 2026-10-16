"""Фоновые задачи (9.2): очередь в той же базе, без отдельного брокера.

Модуль объявляет задачу декоратором `@task("модуль.что")` и ставит её в очередь
`enqueue(...)` внутри своей транзакции — задача появится в очереди, только если
транзакция зафиксирована. Обработчик фоновых задач (`python -m app worker`) берёт задачи по
одной (`FOR UPDATE SKIP LOCKED`), выполняет каждую в своей транзакции — целиком или никак — и
сообщает ход выполнения (6.6). Задачи с `every=` запускаются по расписанию.
"""

import logging
import socket
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.actor import Actor
from app.core.config import config
from app.core.db import Base, transaction
from app.core.errors import AppError

CHANNEL = "core_jobs"
log = logging.getLogger(__name__)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # queued → running → done | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScheduleRun(Base):
    """Когда задача по расписанию запускалась последний раз."""

    __tablename__ = "schedule_run"
    __table_args__ = {"schema": "core"}

    kind: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID, ForeignKey("core.job.id",
                                                                      ondelete="SET NULL"))


class WorkerBeat(Base):
    """Обработчик фоновых задач жив — для страницы состояния (8.5 п. 4)."""

    __tablename__ = "worker_beat"
    __table_args__ = {"schema": "core"}

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Progress:
    """Ход выполнения задачи; пишется отдельной короткой транзакцией, чтобы его было видно
    до окончания задачи."""

    def __init__(self, job_id: uuid.UUID):
        self.job_id = job_id

    def __call__(self, done: int, total: int | None = None, message: str | None = None) -> None:
        with transaction() as s:
            values: dict[str, Any] = {"progress_done": done, "progress_total": total}
            if message is not None:
                values["message"] = message
            s.execute(update(Job).where(Job.id == self.job_id).values(**values))


Handler = Callable[[Session, dict[str, Any], Progress], dict[str, Any] | None]


@dataclass(frozen=True)
class TaskDef:
    kind: str
    handler: Handler
    title: str
    every: timedelta | None = None


_registry: dict[str, TaskDef] = {}


def task(kind: str, title: str, *, every: timedelta | None = None) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        _registry[kind] = TaskDef(kind, handler, title, every)
        return handler

    return register


def registered() -> dict[str, TaskDef]:
    return dict(_registry)


def enqueue(session: Session, kind: str, payload: dict[str, Any] | None = None,
            actor: Actor | None = None) -> uuid.UUID:
    if kind not in _registry:
        raise ValueError(f"unknown task {kind}")
    job = Job(id=uuid.uuid4(), kind=kind, payload=payload or {}, status="queued",
              created_by=actor.user_id if actor else None)
    session.add(job)
    session.flush()
    session.execute(select(func.pg_notify(CHANNEL, str(job.id))))
    return job.id


def _claim() -> Job | None:
    with transaction() as s:
        job = s.scalars(select(Job).where(Job.status == "queued").order_by(Job.created_at)
                        .limit(1).with_for_update(skip_locked=True)).first()
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        return job


def _finish(job_id: uuid.UUID, **values: Any) -> None:
    with transaction() as s:
        s.execute(update(Job).where(Job.id == job_id)
                  .values(finished_at=datetime.now(UTC), **values))


def run_one() -> bool:
    """Выполнить одну задачу из очереди; False — очередь пуста."""
    job = _claim()
    if job is None:
        return False
    definition = _registry.get(job.kind)
    if definition is None:
        _finish(job.id, status="failed", error=f"Неизвестная задача «{job.kind}».")
        return True
    try:
        with transaction() as s:
            result = definition.handler(s, job.payload, Progress(job.id))
    except AppError as e:
        _finish(job.id, status="failed", error=e.message)
    except Exception:
        log.error("task %s %s failed:\n%s", job.kind, job.id, traceback.format_exc())
        _finish(job.id, status="failed",
                error="Задача прервалась из-за внутренней ошибки; подробности — в журнале "
                      "работы сервера.")
    else:
        _finish(job.id, status="done", result=result)
    return True


def _schedule() -> None:
    now = datetime.now(UTC)
    for definition in _registry.values():
        if definition.every is None:
            continue
        with transaction() as s:
            s.execute(insert(ScheduleRun)
                      .values(kind=definition.kind, last_run_at=now - definition.every)
                      .on_conflict_do_nothing())
            run = s.get(ScheduleRun, definition.kind, with_for_update={"skip_locked": True})
            if run is None or run.last_run_at + definition.every > now:
                continue
            run.last_run_at = now
            run.job_id = enqueue(s, definition.kind)


def _requeue_interrupted() -> None:
    """Задачи, прерванные остановкой обработчика, — снова в очередь (до трёх попыток)."""
    with transaction() as s:
        s.execute(update(Job).where(Job.status == "running", Job.attempts < 3)
                  .values(status="queued"))
        s.execute(update(Job).where(Job.status == "running")
                  .values(status="failed", finished_at=func.now(),
                          error="Задача трижды прерывалась остановкой сервера."))


def _beat(name: str) -> None:
    with transaction() as s:
        s.execute(insert(WorkerBeat).values(name=name, seen_at=func.now())
                  .on_conflict_do_update(index_elements=["name"],
                                         set_={"seen_at": func.now()}))


def run_worker(stop: Callable[[], bool] = lambda: False) -> None:
    name = socket.gethostname()
    log.info("worker %s: tasks %s", name, ", ".join(sorted(_registry)))
    _requeue_interrupted()
    dsn = config().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as listen:
        listen.execute(f"LISTEN {CHANNEL}")
        last_beat = 0.0
        while not stop():
            if time.monotonic() - last_beat > 30:
                _beat(name)
                _schedule()
                last_beat = time.monotonic()
            while run_one():
                if stop():
                    return
            for _ in listen.notifies(timeout=5.0, stop_after=1):
                pass


def job_view(job: Job) -> dict[str, Any]:
    definition = _registry.get(job.kind)
    return {
        "id": job.id, "kind": job.kind, "title": definition.title if definition else job.kind,
        "status": job.status, "progress": {"done": job.progress_done,
                                           "total": job.progress_total},
        "message": job.message, "result": job.result, "error": job.error,
        "created_at": job.created_at, "finished_at": job.finished_at,
    }


