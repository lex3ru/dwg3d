"""Подключения камер: доступ, секреты и жизненный цикл превью (ADR-0027)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.db import transaction
from app.core.errors import AppError
from app.modules.surveillance import api, stream
from app.modules.surveillance.models import CameraConnection
from tests.conftest import login, make_client
from tests.test_building import building_with_floor
from tests.test_planning import catalog, changes


def camera(admin):
    building, floor = building_with_floor(admin)
    kinds = catalog(admin)
    response = changes(admin, floor["id"], create=[
        {"type_id": kinds["камера"]["id"], "x": 1000, "y": 1000}
    ])
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    return building, item, f"/api/surveillance/cameras/{item['id']}"


def test_save_secret_version_and_preview(admin, monkeypatch):
    _, item, url = camera(admin)
    assert admin.get(url).json()["configured"] is False
    body = {"address": "rtsp://192.168.1.5:554/stream1", "username": "user",
            "password": "private-password", "version": 0}
    response = admin.put(url, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["has_password"] is True
    assert "private-password" not in response.text
    assert admin.put(url, json=body).status_code == 409
    with transaction() as session:
        import uuid
        source = session.get(CameraConnection, uuid.UUID(item["id"]))
        assert b"private-password" not in source.password
        assert api.stream_url(source) == "rtsp://user:private-password@192.168.1.5:554/stream1"
    history = admin.get("/api/journal", params={"ref": f"item:{item['id']}"}).text
    assert "private-password" not in history
    assert "192.168.1.5" not in history
    assert admin.put(url, json={**body, "password": None, "version": 1}).json()["has_password"]

    async def fake_preview(address):
        assert "private-password" in address
        yield b"frame"
    monkeypatch.setattr("app.modules.surveillance.routes.preview", fake_preview)
    response = admin.get(url + "/preview")
    assert response.status_code == 200
    assert response.content == b"frame"
    assert response.headers["cache-control"] == "no-store"
    assert not admin.put(url, json={**body, "password": "", "version": 2}).json()["has_password"]


def test_access_and_no_connection(admin, app):
    building, item, url = camera(admin)
    assert admin.get(url + "/preview").status_code == 404
    admin.put(url, json={"address": "rtsp://camera/stream1", "version": 0})
    # Используем штатное API выдачи доступа, без подмены зависимостей входа.
    response = admin.post("/api/users", json={
        "login": "camera-viewer", "full_name": "Просмотр", "role": "viewer",
        "building_ids": [building["id"]], "password": "Viewer-pass-123",
    })
    assert response.status_code == 201, response.text
    with make_client(app) as viewer:
        login(viewer, "camera-viewer", "Viewer-pass-123")
        changed = viewer.post("/api/auth/password", json={
            "current": "Viewer-pass-123", "new": "Viewer-final-123"
        })
        assert changed.status_code == 200, changed.text
        result = viewer.get(url)
        assert result.status_code == 200, result.text
        assert result.json()["configured"]
        assert "address" not in viewer.get(url).json()
        update = viewer.put(url, json={"address": "rtsp://other/live", "version": 1})
        assert update.status_code == 403
        other_building = admin.post("/api/buildings", json={"name": "Другое здание"}).json()
        other_floor = admin.post(f"/api/buildings/{other_building['id']}/floors",
                                 json={"name": "Этаж"}).json()
        placed = changes(admin, other_floor["id"], create=[
            {"type_id": item["type_id"], "x": 1000, "y": 1000}
        ]).json()["items"][0]
        other_url = f"/api/surveillance/cameras/{placed['id']}"
        assert viewer.get(other_url).status_code == 404
        assert viewer.get(other_url + "/preview").status_code == 404
    with make_client(app) as anonymous:
        assert anonymous.get(url).status_code == 401
        assert anonymous.get(url + "/preview").status_code == 401
        link = admin.post("/api/share-links", json={"building_id": building["id"],
                          "until": "2026-12-01"})
        assert link.status_code == 201, link.text
        assert anonymous.post(f"/api/share/{link.json()['token']}").status_code == 200
        assert anonymous.get(url).status_code == 403
        assert anonymous.get(url + "/preview").status_code == 403


@pytest.mark.parametrize("address", ["file:///etc/passwd", "http://localhost", "rtsp:///missing",
                                     "rtsp://user:secret@host/stream", "rtsp://host:bad"])
def test_invalid_source(address):
    with pytest.raises(AppError):
        api.validate_address(address)


def test_close_preview_kills_process(monkeypatch):
    async def run():
        killed = []
        process = SimpleNamespace(stdout=SimpleNamespace(read=AsyncMock(return_value=b"frame")),
                                  returncode=None, kill=lambda: killed.append(True),
                                  wait=AsyncMock())
        slots = asyncio.Semaphore(1)
        monkeypatch.setattr(stream, "slots", slots)
        spawn = AsyncMock(return_value=process)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        frames = stream.preview("rtsp://camera/stream1")
        assert await anext(frames) == b"frame"
        assert "-timeout" in spawn.call_args.args
        assert "-rw_timeout" not in spawn.call_args.args
        assert slots.locked()
        await frames.aclose()
        assert killed == [True]
        process.wait.assert_awaited_once()
        assert not slots.locked()
    asyncio.run(run())


def test_preview_can_continue_in_response_task(monkeypatch):
    async def run():
        output = SimpleNamespace(read=AsyncMock(side_effect=[b"a", b"b", b""]))
        process = SimpleNamespace(stdout=output, returncode=0)
        monkeypatch.setattr(stream, "slots", asyncio.Semaphore(1))
        monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
        frames = stream.preview("rtsp://camera/live")
        assert await anext(frames) == b"a"

        async def response():
            return [chunk async for chunk in frames]

        assert await asyncio.create_task(response()) == [b"b"]
        assert not stream.slots.locked()
    asyncio.run(run())
