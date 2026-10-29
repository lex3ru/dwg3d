"""Очередь запросов процесса (8.1, R-036, ADR-0020): HTTP-запросов одновременно — не больше
соединений пула базы. Лишние ждут здесь, в цикле событий, без потока и соединения, — а не
30 с в пуле, после чего получали 500 «QueuePool limit … timed out». Запрос держит одно
соединение: вход и маршрут работают в одной сессии (core/db.py)."""

import asyncio
from weakref import WeakKeyDictionary

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class Admission:
    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app = app
        self.limit = limit
        # очередь — своя у каждого цикла событий: у процесса uvicorn он один, у тестов — по
        # клиенту, а семафор asyncio принадлежит циклу, в котором впервые ждали
        self._slots: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
            WeakKeyDictionary()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # сокет изменений живёт долго, а соединение берёт на миг
            await self.app(scope, receive, send)
            return
        loop = asyncio.get_running_loop()
        slots = self._slots.get(loop) or self._slots.setdefault(
            loop, asyncio.Semaphore(self.limit)
        )
        await slots.acquire()
        held = True

        def release() -> None:
            nonlocal held
            if held:
                held = False
                slots.release()

        async def sending(message: Message) -> None:
            # сессия базы закрыта до ответа (DB, scope="function"): тело — файл, выгрузку —
            # отдаём, уже не занимая места в очереди
            if message["type"] == "http.response.start":
                release()
            await send(message)

        try:
            await self.app(scope, receive, sending)
        finally:
            release()
