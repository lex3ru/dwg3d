"""Изменения приходят открытым страницам без перезагрузки (6.1 п. 8)."""

import asyncio
import threading
import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app import main
from app.core import events
from app.modules.access import api as access

# тишина в сокете в тестах: больше разрешения часов Windows (15,6 мс) — иначе asyncio считает
# таймер наступившим сразу и сервер шлёт ping сплошным потоком (DWG3D-8)
QUIET = 0.05


def test_admin_receives_changes(admin, monkeypatch) -> None:
    # медленная машина (R-034): тишина дольше PING_AFTER, и ping приходит раньше изменения
    monkeypatch.setattr(main, "PING_AFTER", QUIET)
    with admin.websocket_connect("/api/ws") as ws:
        # изменение до LISTEN не дойдёт никому — сначала дождаться, что канал слушается
        assert events.hub.listening.wait(10), "канал изменений не слушается за 10 с"
        assert ws.receive_json() == {"action": "ping"}
        admin.post("/api/users", json={"login": "petrova", "full_name": "П",
                                       "role": "viewer"})
        deadline = time.monotonic() + 5
        while (message := ws.receive_json())["action"] == "ping":
            assert time.monotonic() < deadline, "за 5 с пришли только ping, изменения нет"
        assert message["action"] == "user.create"
        assert message["entity"].startswith("user:")
        assert "full_name" not in message  # только что изменилось, без данных


def test_anonymous_websocket_is_closed(client) -> None:
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
    assert e.value.code == 4401


def test_session_check_does_not_hold_other_requests(admin, monkeypatch) -> None:
    # сокет проверяет сеанс в базе; пока проверка ждёт базу, процесс отвечает на другие
    # запросы (R-051): иначе стоят все запросы этого процесса uvicorn
    checking, release = threading.Event(), threading.Event()
    real = access.actor_for_token

    def slow(session, token):  # type: ignore[no-untyped-def]
        checking.set()
        release.wait(5)
        return real(session, token)

    monkeypatch.setattr(access, "actor_for_token", slow)

    def connect() -> None:
        with admin.websocket_connect("/api/ws"):
            pass

    socket = threading.Thread(target=connect)
    socket.start()
    try:
        assert checking.wait(5), "сокет не начал проверять сеанс"
        started = time.monotonic()
        assert admin.get("/api/health").status_code == 200
        assert time.monotonic() - started < 1, "запрос ждал, пока сокет проверит сеанс"
    finally:
        release.set()
        socket.join(10)


def test_closed_socket_leaves_no_waiting_tasks(admin, monkeypatch) -> None:
    # сокет закрыт — ожидание изменений отменено, а не брошено (R-051): брошенное висит, пока
    # его не соберёт сборщик мусора, и тогда в журнал сервера — «Task was destroyed but it is
    # pending!» на каждое закрытое соединение
    monkeypatch.setattr(main, "PING_AFTER", QUIET)
    with admin.websocket_connect("/api/ws") as ws:
        assert ws.receive_json() == {"action": "ping"}

    def waiting() -> list[asyncio.Task[object]]:
        return [t for t in asyncio.all_tasks()
                if not t.done() and t.get_coro().__qualname__ == "Queue.get"]  # type: ignore[union-attr]

    deadline = time.monotonic() + 2
    while (left := admin.portal.call(waiting)) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert left == [], "после закрытия сокета осталось ожидание изменений"
