"""Поиск по всему (6.3): каждый модуль добавляет свой источник результатов.

Источник получает сессию, действующего и строку запроса и возвращает найденное, уже
отфильтрованное по правам действующего. Строка сверху группирует результаты по `group`.
"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.actor import Actor


@dataclass(frozen=True)
class Hit:
    group: str  # «Помещения», «Имущество», «Документы»…
    title: str
    subtitle: str
    href: str  # адрес в интерфейсе (6.1 п. 7)


Provider = Callable[[Session, Actor, str], list[Hit]]
_providers: list[Provider] = []


def register(provider: Provider) -> None:
    if provider not in _providers:  # повторная подписка не удваивает (R-013)
        _providers.append(provider)


def search(session: Session, actor: Actor, query: str, limit: int = 30) -> list[Hit]:
    query = query.strip()
    if len(query) < 2:
        return []
    hits: list[Hit] = []
    for provider in _providers:
        hits.extend(provider(session, actor, query))
    return hits[:limit]
