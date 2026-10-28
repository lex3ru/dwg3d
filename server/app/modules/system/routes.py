import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import tasks
from app.core.auth import Admin, CurrentActor
from app.core.db import DB
from app.core.errors import NotFound
from app.modules.journal import api as journal
from app.modules.system import api

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/settings")
def get_settings(_: Admin, session: DB) -> dict[str, Any]:
    return api.all_settings(session)


class SettingsIn(BaseModel):
    version: int
    values: dict[str, Any]


@router.patch("/settings")
def update_settings(body: SettingsIn, actor: Admin, session: DB) -> dict[str, Any]:
    return api.update(session, actor, body.values, body.version)


@router.get("/status")
def status(_: Admin, session: DB) -> dict[str, Any]:
    return api.status(session)


@router.get("/tasks/{job_id}")
def job(job_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    """Ход длительной операции (6.6): свою видит каждый, все — администратор."""
    found = session.get(tasks.Job, job_id)
    if found is None or not (actor.is_admin or found.created_by == actor.user_id):
        raise NotFound("Задача не найдена.")
    return tasks.job_view(found)


@router.post("/tasks/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, actor: CurrentActor, session: DB) -> dict[str, Any]:
    """Отменить длительную операцию (R-026, ADR-0011): свою — каждый, любую — администратор.
    Из очереди задача уходит сразу, выполняемую обработчик останавливает за 1–2 с."""
    found = session.get(tasks.Job, job_id, with_for_update=True)
    if found is None or not (actor.is_admin or found.created_by == actor.user_id):
        raise NotFound("Задача не найдена.")
    tasks.cancel(session, found)
    title = tasks.job_view(found)["title"]
    journal.record(session, actor, "task.cancel", f"Отменена задача «{title}»",
                   entity=f"task:{found.id}")
    return tasks.job_view(found)


@tasks.task("system.purge_journal", "Очистка журнала по сроку хранения",
            every=timedelta(days=1))
def purge_journal(session: Session, _payload: dict[str, Any], _progress: tasks.Progress
                  ) -> dict[str, Any]:
    years = api.get(session, "journal_years")
    cutoff = datetime.now(UTC) - timedelta(days=365 * years + years // 4)
    removed = journal.purge_before(session, cutoff)
    if removed:
        journal.record(session, None, "journal.purge",
                       f"Удалено записей журнала старше {years} лет: {removed}",
                       entity="settings:system")
    return {"removed": removed}
