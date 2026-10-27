"""Настройки установки. Каждая настройка описана здесь: название, значение по умолчанию,
проверка. Модули выше читают их через `get(...)`; новые настройки добавляются в SETTINGS."""

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.config import config
from app.core.errors import AppError, stale
from app.core.tasks import Job, WorkerBeat
from app.modules.journal import api as journal
from app.modules.system.models import Setting


def _years(value: Any) -> int:
    if not isinstance(value, int) or not 1 <= value <= 50:
        raise AppError("Срок хранения — целое число лет от 1 до 50.", field="journal_years")
    return value


def _text(limit: int) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise AppError(f"Не длиннее {limit} знаков.")
        return value.strip()

    return check


@dataclass(frozen=True)
class SettingDef:
    title: str
    default: Any
    check: Callable[[Any], Any]


SETTINGS: dict[str, SettingDef] = {
    # 6.7 п. 3: печатается в шапке документов, отчётов и на наклейках
    "organization_name": SettingDef("Название учреждения", "", _text(300)),
    # 5.7.3: журнал и история хранятся столько лет
    "journal_years": SettingDef("Срок хранения журнала, лет", 5, _years),
}


def register(key: str, definition: SettingDef) -> None:
    """Модули выше добавляют свои настройки (вид инвентарного номера, наклейки…)."""
    SETTINGS.setdefault(key, definition)


def get(session: Session, key: str) -> Any:
    row = session.get(Setting, key)
    return row.value if row is not None else SETTINGS[key].default


def all_settings(session: Session) -> dict[str, Any]:
    rows = {r.key: r for r in session.scalars(select(Setting))}
    return {
        "items": [{"key": k, "title": d.title,
                   "value": rows[k].value if k in rows else d.default}
                  for k, d in SETTINGS.items()],
        "version": sum(r.version for r in rows.values()),
    }


def update(session: Session, actor: Actor, values: dict[str, Any], version: int
           ) -> dict[str, Any]:
    current = all_settings(session)
    if current["version"] != version:
        raise stale("Настройки")
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for key, value in values.items():
        definition = SETTINGS.get(key)
        if definition is None:
            raise AppError(f"Настройки «{key}» нет.", field=key)
        try:
            value = definition.check(value)
        except AppError as e:
            e.field = key
            raise
        old = get(session, key)
        if old == value:
            continue
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value, version=1))
        else:
            row.value = value
            row.version += 1
        before[definition.title] = old
        after[definition.title] = value
    if after:
        session.flush()
        journal.record(session, actor, "settings.update", "Изменены настройки",
                       entity="settings:system", before=before, after=after)
    return all_settings(session)


# ---------------------------------------------------------------- состояние (8.5 п. 4)

def human_size(size: float) -> str:
    for unit in ("байт", "КБ", "МБ", "ГБ"):
        if size < 1024:
            text = f"{size:.0f} {unit}" if unit == "байт" else f"{size:.1f} {unit}"
            return text.replace(".", ",")
        size /= 1024
    return f"{size:.1f} ТБ".replace(".", ",")


def _disk(path: Path) -> dict[str, Any] | None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {"path": str(path), "total": usage.total, "used": usage.used, "free": usage.free}


def _backup() -> dict[str, Any]:
    """Сведения о последней копии пишет сервис резервного копирования (deploy/backup)."""
    status_file = config().backup_dir / "last.json"
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "at": None, "message": "Резервных копий ещё не было."}
    at = data.get("finished_at")
    fresh = False
    if at:
        try:
            fresh = datetime.now(UTC) - datetime.fromisoformat(at) < timedelta(hours=26)
        except ValueError:
            pass
    ok = bool(data.get("ok")) and fresh
    message = data.get("message") or ""
    if data.get("ok") and not fresh:
        message = "Последняя копия старше суток — проверьте сервис резервного копирования."
    return {"ok": ok, "at": at, "message": message, "size": data.get("size"),
            "kept": data.get("kept")}


# проверки модулей выше для страницы состояния: {"name", "ok", "detail"} — например, учёт
# называет единицы в убранных или несуществующих местах (R-028)
_checks: list[Callable[[Session], dict[str, Any]]] = []


def on_status_check(check: Callable[[Session], dict[str, Any]]) -> None:
    _checks.append(check)


def status(session: Session) -> dict[str, Any]:
    db_ok = session.execute(text("SELECT 1")).scalar() == 1
    db_size = session.execute(text("SELECT pg_database_size(current_database())")).scalar()
    beat = session.scalar(select(func.max(WorkerBeat.seen_at)))
    worker_ok = beat is not None and datetime.now(UTC) - beat < timedelta(minutes=2)
    queued = session.scalar(select(func.count()).select_from(Job)
                            .where(Job.status.in_(["queued", "running"])))
    failed = session.scalar(select(func.count()).select_from(Job).where(
        Job.status == "failed", Job.finished_at > datetime.now(UTC) - timedelta(days=1)))
    backup = _backup()
    checks = [
        {"name": "База данных", "ok": db_ok,
         "detail": f"работает, занято {human_size(db_size or 0)}"},
        {"name": "Фоновые задачи", "ok": worker_ok,
         "detail": f"в очереди {queued}, за сутки не выполнено {failed}" if worker_ok
         else "обработчик не отвечает больше 2 минут"},
        {"name": "Резервное копирование", "ok": backup["ok"],
         "detail": backup["message"] or "последняя копия есть"},
        *(check(session) for check in _checks),
    ]
    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
        "backup": backup,
        "disks": [d for d in (_disk(config().data_dir), _disk(config().backup_dir)) if d
                  and not (d["path"] == str(config().backup_dir)
                           and config().backup_dir == config().data_dir)],
        "worker_seen_at": beat,
        "checked_at": datetime.now(UTC),
    }
