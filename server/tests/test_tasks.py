"""Фоновые задачи (9.2, 6.6): очередь в базе, ход выполнения, целиком или никак."""

from typing import Any

from sqlalchemy import select, text

from app.core import tasks
from app.core.db import transaction
from app.core.errors import AppError
from app.modules.journal import api as journal
from app.modules.journal.models import Entry


@tasks.task("test.count", "Тестовая задача")
def _count(session, payload: dict[str, Any], progress: tasks.Progress) -> dict[str, Any]:
    for i in range(payload["n"]):
        progress(i + 1, payload["n"], f"шаг {i + 1}")
    journal.record(session, None, "test.count", "Посчитано", entity="test:1")
    if payload.get("fail"):
        raise AppError("Строка 12: номер 000154 уже занят.")
    return {"n": payload["n"]}


def _job(job_id):  # type: ignore[no-untyped-def]
    with transaction() as s:
        return tasks.job_view(s.get(tasks.Job, job_id))


def test_a_task_runs_and_reports_progress(admin) -> None:
    with transaction() as s:
        job_id = tasks.enqueue(s, "test.count", {"n": 3})
    assert _job(job_id)["status"] == "queued"
    assert tasks.run_one() and not tasks.run_one()
    job = admin.get(f"/api/system/tasks/{job_id}").json()
    assert job["status"] == "done" and job["result"] == {"n": 3}
    assert job["progress"] == {"done": 3, "total": 3} and job["message"] == "шаг 3"


def test_a_failed_task_changes_nothing_and_says_why(admin) -> None:
    with transaction() as s:
        job_id = tasks.enqueue(s, "test.count", {"n": 1, "fail": True})
    tasks.run_one()
    job = _job(job_id)
    assert job["status"] == "failed" and job["error"] == "Строка 12: номер 000154 уже занят."
    with transaction() as s:
        assert not s.scalars(select(Entry).where(Entry.action == "test.count")).all()


def test_a_task_enqueued_in_a_rolled_back_transaction_does_not_exist() -> None:
    try:
        with transaction() as s:
            tasks.enqueue(s, "test.count", {"n": 1})
            raise RuntimeError
    except RuntimeError:
        pass
    assert not tasks.run_one()


def test_scheduled_tasks_are_enqueued_once_per_period() -> None:
    tasks._schedule()
    tasks._schedule()
    with transaction() as s:
        kinds = sorted(s.scalars(select(tasks.Job.kind)))
    assert kinds == ["access.purge_sessions", "inventory.purge_cost_statements",
                     "reports.purge_exports", "system.purge_journal"]


def test_interrupted_tasks_are_requeued() -> None:
    with transaction() as s:
        job_id = tasks.enqueue(s, "test.count", {"n": 1})
        s.execute(text("UPDATE core.job SET status = 'running', attempts = 1"))
    tasks._requeue_interrupted()
    assert _job(job_id)["status"] == "queued"
