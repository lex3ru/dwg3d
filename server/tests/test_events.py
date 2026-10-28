"""Изменения приходят открытым страницам без перезагрузки (6.1 п. 8)."""

import asyncio
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app import main
from app.core import events
from app.core.db import transaction
from app.modules.access import api as access
from tests import test_projects as projects
from tests.conftest import login, make_client
from tests.test_building import building_with_floor
from tests.test_inventory import document, post, setup

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


def next_change(ws) -> dict:  # type: ignore[no-untyped-def,type-arg]
    """Следующее изменение, пропуская ping."""
    deadline = time.monotonic() + 5
    while (message := ws.receive_json())["action"] == "ping":
        assert time.monotonic() < deadline, "за 5 с пришли только ping, изменения нет"
    return message  # type: ignore[no-any-return]


def closed_code(ws) -> int:  # type: ignore[no-untyped-def]
    """Код, с которым сервер закрыл сокет; за 5 с не закрыл — ошибка."""
    deadline = time.monotonic() + 5
    with pytest.raises(WebSocketDisconnect) as e:
        while ws.receive_json():
            assert time.monotonic() < deadline, "сокет не закрыт за 5 с"
    return e.value.code


@contextmanager
def viewer(admin, app, *building_ids: str) -> Iterator[tuple[TestClient, dict]]:  # type: ignore[no-untyped-def,type-arg]
    """«Просмотр» с доступом к зданиям — клиент и учётная запись."""
    account = admin.post("/api/users", json={
        "login": "petrova", "full_name": "Петрова Е. А.", "role": "viewer",
        "building_ids": list(building_ids), "password": "Temporary-1"}).json()["user"]
    with make_client(app) as c:
        login(c, "petrova", "Temporary-1")
        c.post("/api/auth/password", json={"current": "Temporary-1", "new": "Viewer-pass-1"})
        yield c, account


def test_r012_viewer_receives_accounting_changes_but_not_projects(admin, app, monkeypatch
                                                                   ) -> None:
    """«Просмотр» видит изменения учёта своего здания без перезагрузки (6.1 п. 8), а событий
    проектов не получает — проектов он не видит (2.2, R-012)."""
    monkeypatch.setattr(main, "PING_AFTER", QUIET)
    building, rooms, _, k = setup(admin)
    p = projects.project(admin, building["id"], "Перестановка")
    with viewer(admin, app, building["id"]) as (v, _), v.websocket_connect("/api/ws") as ws:
        assert events.hub.listening.wait(10), "канал изменений не слушается за 10 с"
        assert ws.receive_json() == {"action": "ping"}
        r = admin.patch(f"/api/projects/{p['id']}",
                        json={"version": p["version"], "name": "Вариант Б"})
        assert r.status_code == 200, r.text
        post(admin, document(admin, "receipt", {"to_place": rooms["214"]},
                             [{"type_id": k["экг"]["id"], "qty": 1, "price": 85000}]))
        assert next_change(ws)["action"].startswith("inventory.document_")


def test_r012_blocked_user_socket_is_closed_at_once(admin, app, monkeypatch) -> None:
    """Заблокировали — сокет закрывается сразу, не дожидаясь перепроверки по времени
    (R-012): события о самом пользователе перепроверяют сеанс."""
    monkeypatch.setattr(main, "PING_AFTER", QUIET)
    monkeypatch.setattr(main, "RECHECK_AFTER", 60, raising=False)
    building, _ = building_with_floor(admin)
    with viewer(admin, app, building["id"]) as (v, account), v.websocket_connect("/api/ws") as ws:
        assert events.hub.listening.wait(10), "канал изменений не слушается за 10 с"
        assert ws.receive_json() == {"action": "ping"}
        assert admin.post(f"/api/users/{account['id']}/block").status_code == 200
        assert closed_code(ws) == 4401


def test_r012_ended_session_socket_is_closed(admin, monkeypatch) -> None:
    """Сеанс кончился без события (истёк, удалён) — сокет закрывается при перепроверке
    раз в RECHECK_AFTER (R-012)."""
    monkeypatch.setattr(main, "PING_AFTER", QUIET)
    monkeypatch.setattr(main, "RECHECK_AFTER", QUIET, raising=False)
    with admin.websocket_connect("/api/ws") as ws:
        assert ws.receive_json() == {"action": "ping"}
        with transaction() as s:
            s.execute(text("DELETE FROM access.login_session"))
        assert closed_code(ws) == 4401


def test_r012_viewer_given_a_building_receives_its_changes(admin, app, monkeypatch) -> None:
    """Выдали «просмотру» ещё здание — его изменения приходят в уже открытый сокет."""
    monkeypatch.setattr(main, "PING_AFTER", QUIET)
    monkeypatch.setattr(main, "RECHECK_AFTER", 60, raising=False)
    first, _ = building_with_floor(admin)
    second = admin.post("/api/buildings", json={"name": "Стационар", "address": ""}).json()
    with viewer(admin, app, first["id"]) as (v, account), v.websocket_connect("/api/ws") as ws:
        assert events.hub.listening.wait(10), "канал изменений не слушается за 10 с"
        assert ws.receive_json() == {"action": "ping"}
        version = admin.get(f"/api/users/{account['id']}").json()["version"]  # сменил пароль
        r = admin.patch(f"/api/users/{account['id']}", json={
            "version": version, "building_ids": [first["id"], second["id"]]})
        assert r.status_code == 200, r.text
        assert next_change(ws)["action"] == "user.update"
        r = admin.patch(f"/api/buildings/{second['id']}",
                        json={"version": second["version"], "name": "Стационар 2"})
        assert r.status_code == 200, r.text
        # второй клиент на том же приложении — второй слушатель канала: изменение может
        # прийти дважды, поэтому — до нужного
        deadline = time.monotonic() + 5
        while next_change(ws)["entity"] != f"building:{second['id']}":
            assert time.monotonic() < deadline, "изменение второго здания не пришло за 5 с"
