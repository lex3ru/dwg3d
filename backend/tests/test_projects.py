"""Projects as containers of drawings: several drawings, revisions, reports, deletion."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from make_sample import make


@pytest.fixture(scope="module")
def c(tmp_path_factory, pg):
    os.environ["DWG3D_DATA"] = str(tmp_path_factory.mktemp("data"))
    from dwg3d import api
    return TestClient(api.app)


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make(tmp_path_factory.mktemp("dxf") / "sample.dxf")


def _wait(c, did, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        d = c.get(f"/api/drawings/{did}").json()
        if d["status"] in ("done", "error"):
            return d
        time.sleep(0.2)
    raise TimeoutError


def _upload(c, pid, name, content, url=None):
    return c.post(url or f"/api/projects/{pid}/drawings", files={"file": (name, content)})


def test_project_crud(c):
    assert c.post("/api/projects", json={}).status_code == 400
    assert c.post("/api/projects", json={"name": "  "}).status_code == 400
    p = c.post("/api/projects", json={"name": "Клиника", "description": "Корпуса А и Б"})
    assert p.status_code == 201
    p = p.json()
    assert p["name"] == "Клиника" and p["drawings"] == []
    r = c.patch(f"/api/projects/{p['id']}", json={"name": "Клиника на Ленина"}).json()
    assert r["name"] == "Клиника на Ленина" and r["description"] == "Корпуса А и Б"
    assert any(x["id"] == p["id"] for x in c.get("/api/projects").json())
    assert c.get("/api/projects/nope").status_code == 404
    assert c.post("/api/projects/nope/drawings", files={"file": ("a.dxf", b"0")}).status_code == 404
    assert c.delete(f"/api/projects/{p['id']}").status_code == 204
    assert c.get(f"/api/projects/{p['id']}").status_code == 404
    assert all(x["id"] != p["id"] for x in c.get("/api/projects").json())


def test_drawings_revisions_and_report(c, sample):
    pid = c.post("/api/projects", json={"name": "Медцентр"}).json()["id"]
    assert _upload(c, pid, "plan.pdf", b"x").status_code == 400
    a = _upload(c, pid, "korpus_a.dxf", sample.read_bytes()).json()
    b = c.post(f"/api/projects/{pid}/drawings", files={"file": ("korpus_b.dxf", sample.read_bytes())},
               data={"name": "Корпус Б"}).json()
    assert a["project_id"] == pid and a["name"] == "korpus_a"
    a, b = _wait(c, a["id"]), _wait(c, b["id"])
    assert a["status"] == b["status"] == "done" and b["name"] == "Корпус Б"
    assert a["model_url"].startswith(f"/api/drawings/{a['id']}/files/model.glb")
    p = c.get(f"/api/projects/{pid}").json()
    assert {d["id"] for d in p["drawings"]} == {a["id"], b["id"]}
    assert all(d["status"] == "done" and d["floors"] >= 1 for d in p["drawings"])
    assert {d["id"] for d in c.get(f"/api/drawings?project={pid}").json()} == {a["id"], b["id"]}

    fa, fb = a["result"]["floors"][0]["id"], b["result"]["floors"][0]["id"]
    item = {"item": "doc.couch", "at": [2, 2]}
    assert c.post(f"/api/drawings/{a['id']}/placements", json={**item, "id": "x", "floor": fa}).status_code == 201
    assert c.post(f"/api/drawings/{b['id']}/placements", json={**item, "id": "x", "floor": fb}).status_code == 201

    rep = c.get(f"/api/reports/equipment?project={pid}").json()
    assert rep["project"]["name"] == "Медцентр" and rep["qty"] == 2
    assert len(rep["columns"]) == 2 and {col.split(" · ")[0] for col in rep["columns"]} == {"korpus_a", "Корпус Б"}

    # a new revision of the DWG keeps the floors and what stands on them
    r = _upload(c, pid, "korpus_a_v2.dxf", sample.read_bytes(), url=f"/api/drawings/{a['id']}/revision")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert _upload(c, pid, "x.dxf", sample.read_bytes(), url=f"/api/drawings/{a['id']}/revision").status_code == 409
    a2 = _wait(c, a["id"])
    assert a2["status"] == "done" and a2["build"] == 2 and a2["filename"] == "korpus_a_v2.dxf"
    assert [f["id"] for f in a2["view"]["furniture"]] == ["x"] and a2["view"]["furniture"][0]["floor"] == fa

    log = c.get(f"/api/projects/{pid}/audit").json()
    assert {(x["entity"], x["action"]) for x in log} >= {("drawing", "create"), ("drawing", "revision"),
                                                         ("placement", "create")}
    assert {x["drawing_id"] for x in c.get(f"/api/projects/{pid}/audit?drawing={b['id']}").json()} == {b["id"]}

    assert c.delete(f"/api/drawings/{b['id']}").status_code == 204
    assert c.get(f"/api/drawings/{b['id']}").status_code == 404
    assert [d["id"] for d in c.get(f"/api/projects/{pid}").json()["drawings"]] == [a["id"]]
    assert c.get(f"/api/reports/equipment?project={pid}").json()["qty"] == 1

    assert c.delete(f"/api/projects/{pid}").status_code == 204
    assert c.get(f"/api/drawings/{a['id']}").status_code == 404
