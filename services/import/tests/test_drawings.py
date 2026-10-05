"""Uploading drawings, building them, reading the results."""
from __future__ import annotations

import json

from sqlalchemy import select, text
from twin_chassis.db import outbox

from .conftest import BUILDING, upload

API = "/api/import/v1"


async def events(app) -> list[dict]:
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        return [e for (e,) in rows]


async def test_upload_build_and_read(client, app, worker, tokens, sample):
    r = await upload(client, tokens, sample, name="Корпус А.dxf")
    assert r.status_code == 201, r.text
    drawing = r.json()
    assert drawing["building_id"] == BUILDING and drawing["name"] == "Корпус А.dxf" and drawing["file_n"] == 1
    assert drawing["build"]["status"] == "queued" and drawing["current_build_id"] is None

    assert await worker.run_once() is True
    assert await worker.run_once() is False                        # the queue is empty

    admin = tokens.admin()
    drawing = (await client.get(f"{API}/drawings/{drawing['id']}", headers=admin)).json()
    build = drawing["build"]
    assert build["status"] == "done" and build["progress"] == 1 and drawing["current_build_id"] == build["id"]
    assert [d["id"] for d in (await client.get(f"{API}/drawings", params={"building_id": BUILDING},
                                               headers=admin)).json()["items"]] == [drawing["id"]]

    result = (await client.get(f"{API}/builds/{build['id']}/result", headers=admin)).json()
    assert result["building_id"] == BUILDING
    floors = result["result"]["floors"]
    assert [f["level"] for f in floors] == [1, 2] and all(len(f["rooms"]) == 2 for f in floors)

    model = await client.get(f"{API}/builds/{build['id']}/files/model.glb", headers=admin)
    assert model.status_code == 200 and model.content[:4] == b"glTF"
    assert model.headers["content-type"] == "model/gltf-binary" and "immutable" in model.headers["cache-control"]
    plan = await client.get(f"{API}/builds/{build['id']}/files/{floors[0]['plan']}", headers=admin)
    assert len(plan.json()["rooms"]) == 2
    for bad in ("cache/x.pkl", "nosuch.glb", "plans/floor_zz.json"):
        assert (await client.get(f"{API}/builds/{build['id']}/files/{bad}", headers=admin)).status_code == 404

    happened = await events(app)
    assert [e["type"] for e in happened] == ["import.drawing.uploaded", "import.build.started", "import.build.finished"]
    assert all(e["building_id"] == BUILDING for e in happened)
    assert happened[2]["data"] == {"build_id": build["id"], "drawing_id": drawing["id"], "n": 1, "floors": 2,
                                   "rooms": 4, "warnings": happened[2]["data"]["warnings"], "quality": "ok"}


async def test_rights(client, tokens, sample):
    drawing = (await upload(client, tokens, sample)).json()
    files = {"file": ("plan.dxf", sample, "application/octet-stream")}
    form = {"building_id": BUILDING}

    assert (await client.post(f"{API}/drawings", files=files, data=form)).status_code == 401
    assert (await client.get(f"{API}/drawings/{drawing['id']}")).status_code == 401

    user = tokens.bearer("user-1")
    assert (await client.post(f"{API}/drawings", files=files, data=form, headers=user)).status_code == 403
    assert (await client.get(f"{API}/drawings/{drawing['id']}", headers=user)).status_code == 403

    # another service may read, but not change
    service = tokens.bearer("svc", login="twin-svc-buildings", service=True)
    assert (await client.get(f"{API}/drawings/{drawing['id']}", headers=service)).status_code == 200
    assert (await client.post(f"{API}/drawings", files=files, data=form, headers=service)).status_code == 403
    assert (await client.delete(f"{API}/drawings/{drawing['id']}", headers=service)).status_code == 403


async def test_invalid_uploads(client, tokens, sample):
    r = await upload(client, tokens, sample, name="plan.pdf")
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "file"
    assert (await upload(client, tokens, b"", name="empty.dxf")).status_code == 422
    r = await upload(client, tokens, sample, config=json.dumps({"units": "parsecs"}))
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "config"
    assert (await upload(client, tokens, sample, config="{not json")).status_code == 422
    r = await client.post(f"{API}/drawings", headers=tokens.admin(), files={"file": ("p.dxf", sample)}, data={})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "building_id"


async def test_same_file_again_does_not_build(client, worker, tokens, sample):
    drawing = (await upload(client, tokens, sample)).json()
    admin, url = tokens.admin(), f"{API}/drawings/{drawing['id']}/files"
    again = {"file": ("plan.dxf", sample, "application/octet-stream")}

    busy = await client.post(url, files=again, headers=admin)          # the first build is still queued
    assert busy.status_code == 409 and busy.json()["code"] == "busy"
    await worker.run_once()

    same = await client.post(url, files=again, headers=admin)
    assert same.status_code == 200 and same.json()["unchanged"] is True
    assert same.json()["build"]["n"] == 1 and same.json()["build"]["status"] == "done"
    assert await worker.run_once() is False

    changed = await client.post(url, files={"file": ("plan_v2.dxf", sample + b"\n", "application/octet-stream")},
                                headers=admin)
    assert changed.status_code == 200 and changed.json()["unchanged"] is False
    assert changed.json()["file_n"] == 2 and changed.json()["build"] == {**changed.json()["build"], "n": 2,
                                                                         "status": "queued"}
    assert await worker.run_once() is True


async def test_broken_file_fails_with_a_message(client, app, worker, tokens):
    drawing = (await upload(client, tokens, b"this is not a drawing at all", name="broken.dxf")).json()
    await worker.run_once()

    build = (await client.get(f"{API}/drawings/{drawing['id']}", headers=tokens.admin())).json()["build"]
    assert build["status"] == "error" and build["error"] and "Traceback" not in build["error"]
    failed = (await events(app))[-1]
    assert failed["type"] == "import.build.failed" and failed["data"]["message"] == build["error"]
    r = await client.get(f"{API}/builds/{build['id']}/result", headers=tokens.admin())
    assert r.status_code == 409 and r.json()["code"] == "not_ready"


async def test_rebuild_with_corrections(client, worker, tokens, sample):
    drawing = (await upload(client, tokens, sample)).json()
    await worker.run_once()
    admin = tokens.admin()
    build = (await client.get(f"{API}/drawings/{drawing['id']}", headers=admin)).json()["build"]
    floor = (await client.get(f"{API}/builds/{build['id']}/result", headers=admin)).json()["result"]["floors"][0]

    # the 2D editor names a room; the correction is pinned to the floor's sheet
    edits = {floor["id"]: {"rooms": [{"at": [2.0, 5.0], "name": "Холл"}]}}
    r = await client.post(f"{API}/drawings/{drawing['id']}/builds", json={"config": {"edits": edits}}, headers=admin)
    assert r.status_code == 202 and r.json()["build"]["n"] == 2
    again = await client.post(f"{API}/drawings/{drawing['id']}/builds", json={}, headers=admin)
    assert again.status_code == 409 and again.json()["code"] == "busy"
    await worker.run_once()

    build = (await client.get(f"{API}/drawings/{drawing['id']}", headers=admin)).json()["build"]
    assert build["status"] == "done"
    floor = (await client.get(f"{API}/builds/{build['id']}/result", headers=admin)).json()["result"]["floors"][0]
    assert "Холл" in [room["name"] for room in floor["rooms"]]
    config = (await client.get(f"{API}/drawings/{drawing['id']}/config", headers=admin)).json()["config"]
    assert config["edits"][floor["id"]]["_anchor"]

    bad = await client.post(f"{API}/drawings/{drawing['id']}/builds", json={"config": {"units": "parsecs"}},
                            headers=admin)
    assert bad.status_code == 422

    # the drawing with the correction drawn in
    dxf = await client.get(f"{API}/drawings/{drawing['id']}/export", params={"format": "dxf"}, headers=admin)
    assert dxf.status_code == 200 and b"SECTION" in dxf.content[:200]
    assert "attachment" in dxf.headers["content-disposition"]


async def test_export_needs_corrections(client, worker, tokens, sample):
    drawing = (await upload(client, tokens, sample)).json()
    url, admin = f"{API}/drawings/{drawing['id']}/export", tokens.admin()
    assert (await client.get(url, headers=admin)).json()["code"] == "not_ready"
    await worker.run_once()
    r = await client.get(url, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "nothing_to_export"
    assert (await client.get(url, params={"format": "pdf"}, headers=admin)).status_code == 422


async def test_build_whose_worker_died_is_failed(client, app, worker, tokens, sample):
    drawing = (await upload(client, tokens, sample)).json()
    assert await worker.claim() is not None                       # taken, and then the worker dies
    assert await worker.reap() == 0                                # its heartbeat is still fresh
    async with app.state.db.begin() as session:
        await session.execute(text("UPDATE builds SET heartbeat_at = now() - interval '10 minutes'"))
    assert await worker.reap() == 1

    build = (await client.get(f"{API}/drawings/{drawing['id']}", headers=tokens.admin())).json()["build"]
    assert build["status"] == "error" and "перестал отвечать" in build["error"]
    assert (await events(app))[-1]["type"] == "import.build.failed"
    # and the drawing can be built again
    r = await client.post(f"{API}/drawings/{drawing['id']}/builds", json={}, headers=tokens.admin())
    assert r.status_code == 202


async def test_delete(client, app, worker, tokens, sample):
    drawing = (await upload(client, tokens, sample)).json()
    admin = tokens.admin()
    assert (await client.delete(f"{API}/drawings/{drawing['id']}", headers=admin)).status_code == 204
    assert (await client.get(f"{API}/drawings/{drawing['id']}", headers=admin)).status_code == 404
    assert (await client.delete(f"{API}/drawings/{drawing['id']}", headers=admin)).status_code == 404
    assert (await events(app))[-1]["type"] == "import.drawing.deleted"
    assert await worker.run_once() is False                        # its queued build is not run


async def test_progress_is_announced(client, app, worker, tokens, sample):
    heard: list[dict] = []
    bus = app.state.bus
    import asyncio
    for _ in range(50):
        if bus.connected:
            break
        await asyncio.sleep(0.1)
    sub = await bus.nc.subscribe(bus.live + "import.build.progress")
    await upload(client, tokens, sample)
    await worker.run_once()
    await asyncio.sleep(0.2)
    while sub.pending_msgs:
        heard.append(json.loads((await sub.next_msg(timeout=1)).data))
    assert heard and heard[-1]["data"]["stage"] == "done" and heard[-1]["data"]["progress"] == 1
    from twin_chassis import events as contract
    for event in heard:
        contract.check(event)
