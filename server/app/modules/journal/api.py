"""Программный интерфейс журнала для других модулей.

Каждое изменение данных пишется вызовом `record(...)` в той же транзакции, что и само
изменение (9.2 п. 3): нет изменения без записи и записи без изменения.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import String, bindparam, cast, delete, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.core import events
from app.core.actor import Actor
from app.modules.journal.models import Entry

SYSTEM = "система"


def record(session: Session, actor: Actor | None, action: str, summary: str, *,
           entity: str, refs: Iterable[str] = (), before: Mapping[str, Any] | None = None,
           after: Mapping[str, Any] | None = None, actor_name: str | None = None) -> None:
    all_refs = list(dict.fromkeys([entity, *refs]))
    if actor is not None:
        all_refs.append(f"user:{actor.user_id}")
        all_refs = list(dict.fromkeys(all_refs))
    session.add(Entry(
        actor_id=actor.user_id if actor else None,
        actor_name=actor_name or (actor.full_name if actor else SYSTEM),
        action=action, summary=summary, entity=entity, refs=all_refs,
        before=_plain(before), after=_plain(after),
    ))
    # сообщение канала PostgreSQL — не больше 8000 байт: при больших пачках (ряд из сотни
    # светильников) хватает того, что изменилось, без полного перечня. Здание и этаж — сразу
    # за сущностью: по ним изменение доходит до «просмотра» этого здания (R-012)
    where = [r for r in all_refs if r.startswith(("building:", "floor:"))]
    events.publish(session, {"action": action, "entity": entity,
                             "refs": list(dict.fromkeys([entity, *where, *all_refs]))[:40]})


def changes(before: Mapping[str, Any], after: Mapping[str, Any]
            ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Только то, что изменилось: (было, стало)."""
    keys = [k for k in after if before.get(k) != after.get(k)]
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def _plain(values: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if values is None:
        return None
    out: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, (set, frozenset, tuple)):
            value = sorted(str(v) for v in value)
        elif isinstance(value, list):
            value = [v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
                     for v in value]
        elif not isinstance(value, (str, int, float, bool, type(None), dict)):
            value = str(value)
        out[key] = value
    return out


def feed(session: Session, *, ref: str | None = None, actor_id: str | None = None,
         action: str | None = None, since: datetime | None = None,
         until: datetime | None = None, text_query: str | None = None,
         before_id: int | None = None, limit: int = 50) -> list[Entry]:
    """Лента: новые сверху; `before_id` — продолжить с записи старше этой."""
    query = select(Entry).order_by(Entry.id.desc()).limit(min(limit, 200))
    if ref:
        query = query.where(Entry.refs.contains([ref]))
    if actor_id:
        query = query.where(Entry.actor_id == actor_id)
    if action:
        query = query.where(Entry.action.startswith(action))
    if since:
        query = query.where(Entry.at >= since)
    if until:
        query = query.where(Entry.at < until)
    if text_query:
        query = query.where(Entry.summary.ilike(f"%{text_query}%"))
    if before_id:
        query = query.where(Entry.id < before_id)
    return list(session.scalars(query))


def purge_before(session: Session, cutoff: datetime) -> int:
    """Удалить записи старше срока хранения (5.7.3) — единственное разрешённое удаление."""
    session.execute(text("SET LOCAL journal.purge = 'on'"))
    result = session.execute(delete(Entry).where(Entry.at < cutoff))
    session.execute(text("SET LOCAL journal.purge = 'off'"))
    return result.rowcount or 0  # type: ignore[attr-defined]


def entries_for(session: Session, refs: list[str]) -> list[Entry]:
    """Все записи, что касаются хоть одной из ссылок (полная выгрузка, 7.4), — по порядку."""
    if not refs:
        return []
    # массив — подзапросом: по готовому списку PostgreSQL оценивает выборку по его значениям,
    # решает, что подойдёт полжурнала, и перебирает его целиком вместо индекса
    # (8.1: 2 с против 30 мс на здание)
    wanted = select(
        cast(bindparam("refs", type_=ARRAY(String(100))), ARRAY(String(100)))
    ).scalar_subquery()
    return list(
        session.scalars(
            select(Entry).where(Entry.refs.overlap(wanted)).order_by(Entry.id), {"refs": refs}
        )
    )
