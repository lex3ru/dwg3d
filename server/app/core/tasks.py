"""Фоновые задачи (9.2): очередь в той же базе, без отдельного брокера.

Модуль объявляет задачу декоратором `@task("модуль.что")` и ставит её в очередь
`enqueue(...)` внутри своей транзакции — задача появится в очереди, только если
транзакция зафиксирована. Обработчик фоновых задач (`python -m app worker`) берёт задачи
(`FOR UPDATE SKIP LOCKED`), выполняет каждую в дочернем процессе и в своей транзакции —
целиком или никак — и сообщает ход выполнения (6.6). Задачи с `every=` запускаются по
расписанию.

ADR-0011: задачу дольше её `timeout` и отменённую обработчик останавливает вместе с
процессом — PostgreSQL сам откатывает её транзакцию, а модуль узнаёт об этом через `on_fail`.
Полосы (`lane`) идут одновременно, в каждой — одна задача: тяжёлый чертёж не держит выгрузки.
Пульс (`heartbeat_at`) говорит другим обработчикам, что задача не брошена (R-013).
"""

import importlib
import json
import logging
import multiprocessing
import os
import signal
import socket
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from multiprocessing.process import BaseProcess
from typing import Any

import psycopg
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.actor import Actor
from app.core.config import config
from app.core.db import Base, engine, transaction
from app.core.errors import AppError, Conflict

if sys.platform != "win32":
    import resource

CHANNEL = "core_jobs"
LANES = ("main", "drawings")  # полосы очереди: в каждой одна задача, полосы — одновременно
SILENCE = timedelta(minutes=2)  # пульса нет дольше — обработчик задачи замолчал (R-013)
PULSE = 5.0  # секунд между пульсами выполняемых задач
CANCELLED = "Задача отменена."
log = logging.getLogger(__name__)


class Job(Base):
    __tablename__ = "job"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # queued → running → done | failed | cancelled
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
    # кто выполняет и когда подавал голос (R-013); отмену просили — обработчик остановит
    worker: Mapped[str | None] = mapped_column(String(200))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
# задача не выполнена (ошибка, таймаут, отмена, сбой): session, payload, причина
FailHook = Callable[[Session, dict[str, Any], str], None]


@dataclass(frozen=True)
class TaskDef:
    kind: str
    handler: Handler
    title: str
    every: timedelta | None = None
    timeout: timedelta = timedelta(minutes=30)
    lane: str = "main"
    on_fail: FailHook | None = None


_registry: dict[str, TaskDef] = {}


def task(kind: str, title: str, *, every: timedelta | None = None,
         timeout: timedelta = timedelta(minutes=30), lane: str = "main",
         on_fail: FailHook | None = None) -> Callable[[Handler], Handler]:
    """timeout — дольше обработчик задачу останавливает; lane — полоса очереди (LANES);
    on_fail — модуль возвращает свои записи в рабочее состояние, когда задача не выполнена:
    её транзакция к этому времени откачена."""
    if lane not in LANES:
        raise ValueError(f"unknown lane {lane}")

    def register(handler: Handler) -> Handler:
        _registry[kind] = TaskDef(kind, handler, title, every, timeout, lane, on_fail)
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


def enqueue_once(session: Session, kind: str, payload: dict[str, Any],
                 actor: Actor | None = None) -> uuid.UUID:
    """Как enqueue, но та же задача с теми же данными, пока прежняя в очереди или выполняется
    (и её не отменяют), — прежняя: двести одинаковых запросов под пиком считают одно один раз
    (R-036). Одновременные запросы ждут друг друга на блокировке до конца транзакции, иначе
    каждый не увидел бы задачу соседа и поставил свою."""
    key = json.dumps([kind, payload], sort_keys=True, ensure_ascii=False)
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
    found = session.scalar(
        select(Job.id).where(Job.kind == kind, Job.payload == payload,
                             Job.status.in_(("queued", "running")),
                             Job.cancel_requested_at.is_(None)).limit(1))
    return found or enqueue(session, kind, payload, actor)


def purge(session: Session, kind: str, finished_before: datetime) -> int:
    """Удалить завершённые задачи вида kind, кончившиеся раньше finished_before, — для задач,
    чей итог нужен недолго, а весит заметно (ведомость стоимости — R-036)."""
    result = session.execute(
        delete(Job).where(Job.kind == kind, Job.status.in_(("done", "failed", "cancelled")),
                          Job.finished_at < finished_before))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def cancel(session: Session, job: Job) -> None:
    """Отменить задачу (строка заблокирована вызывающим): из очереди — сразу, выполняемую
    остановит обработчик."""
    if job.status == "queued":
        _close(session, job, "cancelled", CANCELLED)
    elif job.status == "running":
        if job.cancel_requested_at is None:
            job.cancel_requested_at = datetime.now(UTC)
    else:
        raise Conflict("Задача уже завершилась — отменять нечего.", code="finished")


def _claim(lane: str | None = None, worker: str | None = None) -> Job | None:
    query = select(Job).where(Job.status == "queued")
    if lane == "main":  # и задачи неизвестного вида: там они завершатся ошибкой
        query = query.where(Job.kind.not_in([k for k, d in _registry.items() if d.lane != lane]))
    elif lane is not None:
        query = query.where(Job.kind.in_([k for k, d in _registry.items() if d.lane == lane]))
    with transaction() as s:
        job = s.scalars(query.order_by(Job.created_at).limit(1)
                        .with_for_update(skip_locked=True)).first()
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.started_at = job.heartbeat_at = datetime.now(UTC)
        job.worker = worker
        return job


def _close(session: Session, job: Job, status: str, error: str) -> None:
    """Задача не выполнена: отметить и дать модулю вернуть свои записи (on_fail)."""
    job.status, job.error, job.finished_at = status, error, datetime.now(UTC)
    definition = _registry.get(job.kind)
    if definition is None or definition.on_fail is None:
        return
    try:
        with session.begin_nested():
            definition.on_fail(session, job.payload, error)
    except Exception:
        log.error("task %s %s: on_fail failed:\n%s", job.kind, job.id, traceback.format_exc())


def _fail(job_id: uuid.UUID, error: str, status: str = "failed") -> bool:
    """False — задача уже завершилась сама (успела до остановки)."""
    with transaction() as s:
        job = s.get(Job, job_id, with_for_update=True)
        if job is None or job.status not in ("queued", "running"):
            return False
        _close(s, job, status, error)
        return True


def _execute(job_id: uuid.UUID, kind: str, payload: dict[str, Any],
             memory_mb: int | None = None) -> None:
    """Выполнить взятую задачу. «Готово» пишется в той же транзакции, что и её данные:
    остановленная задача не оставит данных без «готово» и «готово» без данных.
    memory_mb — предел памяти процесса задачи, если он есть (для причины отказа)."""
    definition = _registry.get(kind)
    if definition is None:
        _fail(job_id, f"Неизвестная задача «{kind}».")
        return
    try:
        with transaction() as s:
            result = definition.handler(s, payload, Progress(job_id))
            s.execute(update(Job).where(Job.id == job_id).values(
                status="done", result=result, finished_at=datetime.now(UTC)))
    except AppError as e:
        _fail(job_id, e.message)
    except MemoryError:
        # данные задачи освобождены вместе с её кадрами — на отметку памяти хватит
        limit = f" — больше {memory_mb} МБ" if memory_mb else ""
        log.error("task %s %s: out of memory%s", kind, job_id, limit)
        _fail(job_id, f"Задаче не хватило памяти{limit}: данных слишком много или файл "
                      "устроен необычно. Предел меняет администратор сервера "
                      "(APP_TASK_MEMORY_MB).")
    except Exception:
        log.error("task %s %s failed:\n%s", kind, job_id, traceback.format_exc())
        _fail(job_id, "Задача прервалась из-за внутренней ошибки; подробности — в журнале "
                      "работы сервера.")


def run_one() -> bool:
    """Выполнить одну задачу из очереди в своём процессе (тесты); False — очередь пуста."""
    job = _claim()
    if job is None:
        return False
    _execute(job.id, job.kind, job.payload)
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


def _release(ids: list[uuid.UUID]) -> None:
    """Прерванные задачи — снова в очередь, до трёх попыток; с просьбой отменить — отменены."""
    if not ids:
        return
    with transaction() as s:
        for job in s.scalars(select(Job).where(Job.id.in_(ids), Job.status == "running")
                             .with_for_update(skip_locked=True)):
            if job.cancel_requested_at is not None:
                _close(s, job, "cancelled", CANCELLED)
            elif job.attempts < 3:
                job.status, job.worker, job.heartbeat_at = "queued", None, None
            else:
                _close(s, job, "failed", "Задача трижды прерывалась остановкой сервера.")


def _requeue_interrupted(name: str | None = None) -> None:
    """Задачи замолчавших обработчиков (пульса нет дольше SILENCE) — снова в очередь (R-013).
    name — свой прошлый запуск: при старте обработчика его задачи брошены наверняка."""
    lost = [Job.heartbeat_at.is_(None), Job.heartbeat_at < datetime.now(UTC) - SILENCE]
    if name is not None:
        lost.append(Job.worker == name)
    with transaction() as s:
        ids = list(s.scalars(select(Job.id).where(Job.status == "running", or_(*lost))))
    _release(ids)


def _beat(name: str) -> None:
    with transaction() as s:
        s.execute(insert(WorkerBeat).values(name=name, seen_at=func.now())
                  .on_conflict_do_update(index_elements=["name"],
                                         set_={"seen_at": func.now()}))


def _pulse(name: str) -> None:
    with transaction() as s:
        s.execute(update(Job).where(Job.worker == name, Job.status == "running")
                  .values(heartbeat_at=func.now()))


# ---------------------------------------------------------------- процесс задачи (ADR-0011)


def _data_size() -> int:
    """Сколько данных процесс уже занял, байт (VmData): у процесса задачи — унаследованное от
    обработчика; потоки OpenBLAS дают сотни МБ, и тем больше, чем больше ядер."""
    try:
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmData:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def _limit_memory(memory_mb: int) -> None:
    """Предел памяти процесса задачи (Linux) — memory_mb сверх уже занятого. RLIMIT_DATA
    считает выделенную память — кучу и анонимные отображения, но не библиотеки и не
    зарезервированное адресное пространство."""
    limit = _data_size() + memory_mb * 1024 * 1024
    hard = resource.getrlimit(resource.RLIMIT_DATA)[1]
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))


def _child(job_id: str, kind: str, payload: dict[str, Any], module: str,
           setup: Callable[[], Any] | None, memory_mb: int) -> None:
    if sys.platform != "win32":
        os.setpgrp()  # своя группа: остановка задачи останавливает и её подпроцессы (dwg2dxf)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        _limit_memory(memory_mb)
    # обработчик пропал — задача никому не нужна: Windows не останавливает потомков сам
    parent = multiprocessing.parent_process()
    if parent is not None:
        threading.Thread(target=lambda: (parent.join(), os._exit(1)), daemon=True).start()
    # fork: соединения пула принадлежат обработчику — у процесса задачи свои
    engine().dispose(close=False)
    if kind not in _registry:  # spawn: процесс начат заново, модули не загружены
        if setup is not None:
            setup()
        importlib.import_module(module)
    _execute(uuid.UUID(job_id), kind, payload, memory_mb if sys.platform != "win32" else None)


@dataclass
class _Running:
    job_id: uuid.UUID
    timeout: timedelta
    process: BaseProcess
    deadline: float


def _start(job: Job, setup: Callable[[], Any] | None) -> _Running | None:
    definition = _registry.get(job.kind)
    if definition is None:
        _fail(job.id, f"Неизвестная задача «{job.kind}».")
        return None
    # Linux — fork: модули уже загружены; Windows — только spawn (разработка, ADR-0007)
    context = multiprocessing.get_context("spawn" if sys.platform == "win32" else "fork")
    process = context.Process(
        target=_child, name=f"task {job.kind}", daemon=True,
        args=(str(job.id), job.kind, job.payload, definition.handler.__module__, setup,
              config().task_memory_mb))
    process.start()
    return _Running(job.id, definition.timeout, process,
                    time.monotonic() + definition.timeout.total_seconds())


def _stop(run: _Running) -> None:
    """Остановить процесс задачи вместе с его группой (dwg2dxf); транзакция откатится."""
    if run.process.is_alive():
        if sys.platform != "win32" and run.process.pid is not None:
            try:
                os.killpg(run.process.pid, signal.SIGKILL)
            except OSError:
                pass  # своей группы процесс ещё не завёл
        run.process.kill()
    run.process.join(timeout=10)


def _minutes(span: timedelta) -> str:
    seconds = int(span.total_seconds())
    return f"{seconds // 60} мин" if seconds >= 60 else f"{seconds} с"


def _watch(running: dict[str, _Running]) -> None:
    """Надзор: отмена, срок, процесс задачи завершился."""
    if not running:
        return
    with transaction() as s:
        asked = set(s.scalars(select(Job.id).where(
            Job.id.in_([r.job_id for r in running.values()]),
            Job.cancel_requested_at.is_not(None))))
    for lane, run in list(running.items()):
        if not run.process.is_alive():
            run.process.join()
            # задача завершилась сама — _fail ничего не сделает
            if _fail(run.job_id, f"Задача прервалась аварийно (код {run.process.exitcode}): "
                                 "например, не хватило памяти. Подробности — в журнале работы "
                                 "сервера."):
                log.error("task %s: process exited with %s", run.job_id, run.process.exitcode)
        elif run.job_id in asked:
            _stop(run)
            _fail(run.job_id, CANCELLED, status="cancelled")
        elif time.monotonic() > run.deadline:
            _stop(run)
            if _fail(run.job_id, f"Задача шла дольше {_minutes(run.timeout)} и остановлена."):
                log.warning("task %s: stopped after %s", run.job_id, run.timeout)
        else:
            continue
        del running[lane]


def run_worker(stop: Callable[[], bool] = lambda: False, name: str | None = None,
               setup: Callable[[], Any] | None = None) -> None:
    """Обработчик фоновых задач (ADR-0011). name — имя в пульсе задач (по умолчанию — имя
    хоста); setup — готовит модули в процессе задачи, начатом заново (spawn, Windows)."""
    name = name or socket.gethostname()
    log.info("worker %s: tasks %s", name, ", ".join(sorted(_registry)))
    _requeue_interrupted(name)
    running: dict[str, _Running] = {}
    dsn = config().database_url.replace("postgresql+psycopg://", "postgresql://")
    try:
        with psycopg.connect(dsn, autocommit=True) as listen:
            listen.execute(f"LISTEN {CHANNEL}")
            last_beat = last_pulse = 0.0
            while not stop():
                if time.monotonic() - last_beat > 30:
                    _beat(name)
                    _schedule()
                    _requeue_interrupted()
                    last_beat = time.monotonic()
                if time.monotonic() - last_pulse > PULSE:
                    _pulse(name)
                    last_pulse = time.monotonic()
                _watch(running)
                for lane in LANES:
                    if lane not in running and not stop():
                        job = _claim(lane, name)
                        started = _start(job, setup) if job is not None else None
                        if started is not None:
                            running[lane] = started
                for _ in listen.notifies(timeout=1.0, stop_after=1):
                    pass
    finally:
        # остановка обработчика: задачи — снова в очередь, их выполнит следующий запуск
        for run in running.values():
            _stop(run)
        _release([r.job_id for r in running.values()])


def job_view(job: Job) -> dict[str, Any]:
    definition = _registry.get(job.kind)
    return {
        "id": job.id, "kind": job.kind, "title": definition.title if definition else job.kind,
        "status": job.status, "progress": {"done": job.progress_done,
                                           "total": job.progress_total},
        "message": job.message, "result": job.result, "error": job.error,
        "cancel_requested": job.cancel_requested_at is not None,
        "created_at": job.created_at, "finished_at": job.finished_at,
    }
