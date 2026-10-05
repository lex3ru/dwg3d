"""Engineering layers: network (cable routes), fire alarm, access control, Wi-Fi;
their catalog, specification rows and checks."""
import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from make_sample import make


@pytest.fixture(scope="module")
def c(tmp_path_factory, pg):
    os.environ["DWG3D_DATA"] = str(tmp_path_factory.mktemp("data"))
    from dwg3d import api
    return TestClient(api.app)


@pytest.fixture(scope="module")
def built(c, tmp_path_factory):
    sample = make(tmp_path_factory.mktemp("dxf") / "sample.dxf")
    pid = c.post("/api/projects", json={"name": "Системы"}).json()["id"]
    did = c.post(f"/api/projects/{pid}/drawings", files={"file": ("plan.dxf", sample.read_bytes())}).json()["id"]
    t = time.time()
    while (d := c.get(f"/api/drawings/{did}").json())["status"] not in ("done", "error"):
        assert time.time() - t < 120
        time.sleep(0.2)
    assert d["status"] == "done"
    return pid, d


def test_catalog_of_systems(c, pg):
    cat = c.get("/api/catalog").json()
    cats = {x["id"] for x in cat["categories"]}
    assert {"network", "fire", "access", "wifi"} <= cats
    items = {x["id"]: x for x in cat["items"]}
    assert items["wifi.ap"]["params"] == {"radio": {"tx": 20.0, "range": 40.0}}
    assert items["fire.smoke"]["params"]["detect"]["radius"] == 5.0
    assert c.patch("/api/catalog/items/wifi.ap", json={"params": {"radio": {"tx": 99, "range": 10}}}).status_code == 400
    assert c.patch("/api/catalog/items/wifi.ap", json={"params": {"sonar": {}}}).status_code == 400
    # light sources: luminous flux, power, beam angle, colour temperature
    assert "lighting" in cats
    assert items["light.panel"]["params"] == {"light": {"flux": 3600.0, "power": 36.0, "beam": 120.0, "cct": 4000.0}}
    assert c.patch("/api/catalog/items/light.panel", json={"params": {"light": {"flux": 3600, "power": 36, "beam": 400, "cct": 4000}}}).status_code == 400
    assert c.patch("/api/catalog/items/light.panel", json={"params": {"light": {"flux": 3600}}}).status_code == 400
    # a catalog made before these categories gets them on start-up, edits are kept
    from dwg3d import catalog, db
    from dwg3d.models import CatalogItem
    catalog.update_item("fire.smoke", {"price": 1234})
    with db.session() as s:
        s.execute(delete(CatalogItem).where(CatalogItem.id == "acs.reader"))
    catalog.ensure_seeded()
    items = {x["id"]: x for x in c.get("/api/catalog").json()["items"]}
    assert "acs.reader" in items and items["fire.smoke"]["price"] == 1234


def test_layers_of_systems_and_cables(c, built):
    pid, d = built
    did, fl = d["id"], d["result"]["floors"][0]
    base = f"/api/drawings/{did}/objects"
    made = c.post(f"{base}:batch", json={"ops": [
        {"op": "create", "id": "s1", "floor": fl["id"], "item": "fire.smoke", "at": [2, 2]},
        {"op": "create", "id": "s2", "floor": fl["id"], "item": "wifi.ap", "at": [3, 3]},
        {"op": "create", "id": "s3", "floor": fl["id"], "item": "acs.reader", "at": [1, 1]},
        {"op": "create", "id": "s4", "floor": fl["id"], "item": "net.socket_rj45", "at": [1, 2]},
        {"op": "create", "id": "s5", "floor": fl["id"], "item": "light.panel", "at": [2, 3]},
    ]}).json()["items"]
    lays = {x["id"]: x["kind"] for x in c.get(f"/api/projects/{pid}/layers").json()}
    assert [lays[o["layer"]] for o in made] == ["fire", "wifi", "access", "network", "lighting"]
    net = next(k for k, v in lays.items() if v == "network")
    # a cable route: 3 m + 4 m, 10 % reserve
    r = c.post(base, json={"id": "cab", "geom": "polyline", "layer": net, "floor": fl["id"],
                           "points": [[0, 0], [3, 0], [3, 4]], "props": {"cable": "utp", "reserve": 10}})
    assert r.status_code == 201 and r.json()["props"] == {"cable": "utp", "name": "", "reserve": 10.0}
    assert c.post(base, json={"geom": "polyline", "layer": net, "floor": fl["id"], "points": [[0, 0], [1, 1]],
                              "props": {"cable": "copper"}}).status_code == 400
    rep = c.get(f"/api/reports/equipment?project={pid}").json()
    cable = next(x for x in rep["rows"] if x["item"] == "cable.utp")
    assert cable["unit"] == "м" and cable["qty"] == 7.7 and sum(cable["by"].values()) == 7.7
    assert rep["qty"] == 5                                   # pieces only
    assert c.get(f"/api/reports/equipment?project={pid}&format=xlsx").status_code == 200


def test_fire_check(c, built):
    pid, d = built
    did = d["id"]
    rooms = c.get(f"/api/drawings/{did}/rooms").json()
    got = c.get(f"/api/projects/{pid}/checks").json()["fire"]
    flagged = {x["room_id"] for x in got}
    # the detector s1 stands in one room: that room (if small enough) is fine, the others are flagged
    obj = next(x for x in c.get(f"/api/drawings/{did}/objects").json()["items"] if x["id"] == "s1")
    others = {r["id"] for r in rooms if r["idx"] is not None and r["area"] >= 1 and r["id"] != obj["room"]}
    assert others <= flagged
    assert all(x["need"] > x["has"] for x in got)
