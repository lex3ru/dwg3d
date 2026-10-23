"""Изменения других пользователей — без перезагрузки страницы (6.1 п. 8).

Журнал при каждой записи публикует в канал PostgreSQL `app_changes` короткое сообщение:
что изменилось (ссылки вида "user:<id>", "building:<id>"), без самих данных. Сообщение
уходит, только когда транзакция зафиксирована. Приложение слушает канал и раздаёт
сообщения открытым WebSocket — каждому только то, что ему можно видеть; интерфейс,
получив сообщение, перечитывает затронутые данные.
"""

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import psycopg
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import config

CHANNEL = "app_changes"
log = logging.getLogger(__name__)


def publish(session: Session, message: dict[str, Any]) -> None:
    session.execute(select(func.pg_notify(CHANNEL, json.dumps(message, default=str))))


Subscriber = tuple[asyncio.Queue[dict[str, Any]], Callable[[dict[str, Any]], bool]]


class Hub:
    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.listening = threading.Event()  # канал слушается: изменения дойдут до сокетов

    def subscribe(self, allowed: Callable[[dict[str, Any]], bool]) -> Subscriber:
        sub: Subscriber = (asyncio.Queue(maxsize=200), allowed)
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)

    def _dispatch(self, message: dict[str, Any]) -> None:
        for queue, allowed in list(self._subscribers):
            if allowed(message) and not queue.full():
                queue.put_nowait(message)

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self.listening.clear()
        self._thread = threading.Thread(target=self._listen, name="events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _listen(self) -> None:
        dsn = config().database_url.replace("postgresql+psycopg://", "postgresql://")
        while not self._stop.is_set():
            try:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    self.listening.set()
                    while not self._stop.is_set():
                        for note in conn.notifies(timeout=1.0):
                            message = json.loads(note.payload)
                            assert self._loop is not None
                            self._loop.call_soon_threadsafe(self._dispatch, message)
            except Exception:  # база перезапускается — переподключаемся
                self.listening.clear()
                log.warning("events: lost the database connection, reconnecting", exc_info=True)
                self._stop.wait(2.0)


hub = Hub()
