"""Обработчик фоновых задач (ADR-0011): задача идёт в дочернем процессе. Таймаут, отмена и сбой
останавливают её, но не очередь (R-026); полосы не дают тяжёлой задаче держать остальные; в
очередь возвращаются только задачи «молчащих» обработчиков (R-013)."""

import multiprocessing
import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from app.core import tasks
from app.core.config import config
from app.core.db import transaction
from app.modules.journal import api as journal
from app.modules.journal.models import Entry


def _sleep(session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    progress(0, 1, "сплю")
    time.sleep(payload.get("seconds", 120))
    journal.record(session, None, "test.slept", "Проспал", entity=f"test:{payload['tag']}")
    return {}


def _failed(session, payload: dict[str, Any], error: str) -> None:
    journal.record(session, None, "test.on_fail", error, entity=f"test:{payload['tag']}")


tasks.task("test.heavy", "Тяжёлая задача", lane="drawings", timeout=timedelta(minutes=5),
           on_fail=_failed)(_sleep)
tasks.task("test.slow", "Долгая задача", timeout=timedelta(seconds=3), on_fail=_failed)(_sleep)


@tasks.task("test.quick", "Быстрая задача")
def _quick(session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    journal.record(session, None, "test.quick", "Сделано", entity=f"test:{payload.get('tag')}")
    return {"pid": os.getpid()}


@tasks.task("test.crash", "Задача, которая роняет процесс", on_fail=_failed)
def _crash(session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    # так процесс задачи убивает нехватка памяти или сбой в C-библиотеке; в процессе тестов
    # (до ADR-0011 задача шла в процессе обработчика) — не ронять
    if multiprocessing.parent_process() is None:
        raise RuntimeError("задача должна идти в дочернем процессе")
    os._exit(9)


@tasks.task("test.hungry", "Задача, которой не хватает памяти", on_fail=_failed)
def _hungry(session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    blocks = [bytearray(64 * 1024 * 1024) for _ in range(payload["blocks"])]
    return {"mb": 64 * len(blocks)}


@contextmanager
def worker(name: str = "test-worker") -> Iterator[None]:
    """Обработчик в потоке тестов; задачи — в его дочерних процессах."""
    stop = threading.Event()
    thread = threading.Thread(target=tasks.run_worker, args=(stop.is_set,),
                              kwargs={"name": name}, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=60)
        assert not thread.is_alive(), "обработчик не остановился"


def enqueue(kind: str, **payload: Any) -> uuid.UUID:
    with transaction() as s:
        return tasks.enqueue(s, kind, payload)


def job(job_id: uuid.UUID) -> dict[str, Any]:
    with transaction() as s:
        return tasks.job_view(s.get(tasks.Job, job_id))


def wait(job_id: uuid.UUID, *statuses: str, timeout: float = 40) -> dict[str, Any]:
    """Дождаться статуса; запас — на запуск процесса в Windows (spawn импортирует модули)."""
    deadline = time.monotonic() + timeout
    while (found := job(job_id))["status"] not in statuses and time.monotonic() < deadline:
        time.sleep(0.2)
    return found


def journal_of(tag: str) -> list[tuple[str, str]]:
    with transaction() as s:
        return [(e.action, e.summary) for e in s.scalars(
            select(Entry).where(Entry.entity == f"test:{tag}").order_by(Entry.at))]


def test_r026_a_heavy_task_does_not_hold_the_queue_and_can_be_cancelled(admin) -> None:
    """Пока в полосе чертежей идёт тяжёлая задача, остальные выполняются. Выполняемую задачу
    отменяют: процесс останавливается, её изменения откатываются, модуль узнаёт об отмене."""
    heavy = enqueue("test.heavy", tag="heavy")
    quick = enqueue("test.quick", tag="quick")
    with worker():
        assert wait(quick, "done")["status"] == "done"
        assert job(heavy)["status"] == "running"
        r = admin.post(f"/api/system/tasks/{heavy}/cancel")
        assert r.status_code == 200, r.text
        assert wait(heavy, "cancelled", timeout=15)["status"] == "cancelled"
    assert [a for a, _ in journal_of("heavy")] == ["test.on_fail"]
    # задачи идут не в процессе обработчика
    assert job(quick)["result"]["pid"] != os.getpid()


def test_r026_a_task_longer_than_its_timeout_is_stopped(admin) -> None:
    slow = enqueue("test.slow", tag="slow", seconds=120)
    with worker():
        stopped = wait(slow, "failed")
        after = enqueue("test.quick", tag="after")
        assert wait(after, "done")["status"] == "done"
    assert stopped["status"] == "failed" and "дольше" in stopped["error"], stopped
    assert journal_of("slow") == [("test.on_fail", stopped["error"])]


def test_r026_a_crashed_task_fails_and_the_worker_goes_on() -> None:
    crash = enqueue("test.crash", tag="crash")
    with worker():
        failed = wait(crash, "failed")
        after = enqueue("test.quick", tag="after")
        assert wait(after, "done")["status"] == "done"
    assert failed["status"] == "failed" and failed["error"], failed
    assert [a for a, _ in journal_of("crash")] == ["test.on_fail"]


@pytest.mark.skipif(sys.platform == "win32", reason="предел памяти процесса (setrlimit) — Linux")
def test_r026_a_task_out_of_memory_fails_and_the_worker_goes_on(monkeypatch) -> None:
    """Кривой чертёж за минуту съедает десятки ГБ. Процесс задачи упирается в предел памяти
    (APP_TASK_MEMORY_MB сверх занятого обработчиком): задача не выполнена с понятной
    причиной, модуль узнаёт об этом, обработчик работает дальше."""
    monkeypatch.setattr(config(), "task_memory_mb", 256)
    hungry = enqueue("test.hungry", tag="hungry", blocks=32)  # 2 ГБ
    with worker():
        failed = wait(hungry, "failed")
        after = enqueue("test.quick", tag="after")
        assert wait(after, "done")["status"] == "done"
    assert failed["status"] == "failed" and "не хватило памяти" in failed["error"], failed
    assert "256 МБ" in failed["error"]
    assert [a for a, _ in journal_of("hungry")] == ["test.on_fail"]


def test_r026_a_queued_task_is_cancelled_at_once(admin) -> None:
    slow = enqueue("test.slow", tag="queued")
    r = admin.post(f"/api/system/tasks/{slow}/cancel")
    assert r.status_code == 200, r.text
    assert job(slow)["status"] == "cancelled"
    assert [a for a, _ in journal_of("queued")] == ["test.on_fail"]
    # отменённую и выполненную задачу отменить нельзя; обработчик отменённую не берёт
    assert admin.post(f"/api/system/tasks/{slow}/cancel").status_code == 409
    done = enqueue("test.quick", tag="done")
    assert tasks.run_one() and not tasks.run_one()
    assert job(done)["status"] == "done"
    assert admin.post(f"/api/system/tasks/{done}/cancel").status_code == 409


def _running(worker_name: str, beat: datetime) -> uuid.UUID:
    with transaction() as s:
        found = tasks.Job(id=uuid.uuid4(), kind="test.quick", payload={"tag": worker_name},
                          status="running", attempts=1, worker=worker_name, heartbeat_at=beat,
                          started_at=beat)
        s.add(found)
        return found.id


def test_r013_only_tasks_of_silent_workers_are_requeued() -> None:
    """Задачу живого обработчика (пульс свежий) другой обработчик не трогает; задачи
    замолчавшего обработчика и прошлого запуска этого же — выполняет заново."""
    now = datetime.now(UTC)
    alive = _running("other", now)
    silent = _running("silent", now - timedelta(minutes=10))
    mine = _running("me", now)
    with worker("me"):
        assert wait(silent, "done")["status"] == "done"
        assert wait(mine, "done")["status"] == "done"
        time.sleep(2)
        assert job(alive)["status"] == "running"
    with transaction() as s:
        assert s.get(tasks.Job, alive).worker == "other"
