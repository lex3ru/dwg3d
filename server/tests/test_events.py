"""Изменения приходят открытым страницам без перезагрузки (6.1 п. 8)."""

import pytest
from starlette.websockets import WebSocketDisconnect


def test_admin_receives_changes(admin) -> None:
    with admin.websocket_connect("/api/ws") as ws:
        admin.post("/api/users", json={"login": "petrova", "full_name": "П",
                                       "role": "viewer"})
        message = ws.receive_json()
        assert message["action"] == "user.create"
        assert message["entity"].startswith("user:")
        assert "full_name" not in message  # только что изменилось, без данных


def test_anonymous_websocket_is_closed(client) -> None:
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
    assert e.value.code == 4401
