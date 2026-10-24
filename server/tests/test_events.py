"""Изменения приходят открытым страницам без перезагрузки (6.1 п. 8)."""

import time

import pytest
from starlette.websockets import WebSocketDisconnect

from app import main
from app.core import events


def test_admin_receives_changes(admin, monkeypatch) -> None:
    # медленная машина (R-034): тишина дольше PING_AFTER, и ping приходит раньше изменения
    monkeypatch.setattr(main, "PING_AFTER", 0.01)
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
