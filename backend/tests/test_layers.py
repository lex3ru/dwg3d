"""Layers of a project, their objects, rooms that keep their ids, the room report."""
import io
import os
import time

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from make_sample import make


@pytest.fixture(scope="module")
def c(tmp_path_factory, pg):
    os.environ["DWG3D_DATA"] = str(tmp_path_factory.mktemp("data"))
    from dwg3d import api
    return TestClient(api.app)


@pytest.fixture(scope="module")
def built(c, tmp_path_factory):
    """A project with one built drawing: (project id, drawing JSON)."""
    sample = make(tmp_path_factory.mktemp("dxf") / "sample.dxf")
    pid = c.post("/api/projects", json={"name": "Слои"}).json()["id"]
    did = c.post(f"/api/projects/{pid}/drawings", files={"file": ("plan.dxf", sample.read_bytes())}).json()["id"]
    return pid, _wait(c, did)


def _wait(c, did, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        d = c.get(f"/api/drawings/{did}").json()
        if d["status"] in ("done", "error"):
            assert d["status"] == "done", d.get("error")
            return d
        time.sleep(0.2)
    raise TimeoutError


def test_layer_kinds_and_crud(c, built):
    pid, d = built
    got = c.get("/api/layer-kinds").json()
    kinds = {k["kind"]: k for k in got["kinds"]}
    assert {"furniture", "cctv", "routes", "zones"} <= set(kinds) and kinds["cctv"]["categories"] == ["security"]
    assert "dirty" in got["flows"] and ["clean", "dirty"] in got["flow_conflicts"] and "clean" in got["zone_kinds"]
    assert c.post(f"/api/projects/{pid}/layers", json={"kind": "nope"}).status_code == 400
    lay = c.post(f"/api/projects/{pid}/layers", json={"kind": "furniture", "name": "Мебель — вариант Б"})
    assert lay.status_code == 201
    lay = lay.json()
    assert lay["name"] == "Мебель — вариант Б" and lay["visible"] and not lay["locked"] and lay["count"] == 0
    r = c.patch(f"/api/projects/{pid}/layers/{lay['id']}", json={"visible": False, "version": lay["version"]})
    assert r.status_code == 200 and r.json()["visible"] is False and r.json()["version"] == lay["version"] + 1
    assert c.patch(f"/api/projects/{pid}/layers/{lay['id']}", json={"name": "x", "version": lay["version"]}).status_code == 409
    assert c.patch(f"/api/projects/{pid}/layers/{lay['id']}", json={"visible": "yes"}).status_code == 400
    assert any(x["id"] == lay["id"] for x in c.get(f"/api/projects/{pid}/layers").json())
    assert c.delete(f"/api/projects/{pid}/layers/{lay['id']}").status_code == 204
    assert c.patch(f"/api/projects/{pid}/layers/{lay['id']}", json={"name": "y"}).status_code == 404


def test_objects_in_layers(c, built):
    pid, d = built
    did, fid = d["id"], d["result"]["floors"][0]["id"]
    base = f"/api/drawings/{did}/objects"
    couch = c.post(base, json={"id": "couch", "floor": fid, "item": "doc.couch", "at": [2, 2]}).json()
    cam = c.post(base, json={"id": "cam", "floor": fid, "item": "sec.dome", "at": [3, 3]}).json()
    layers = {x["id"]: x for x in c.get(f"/api/projects/{pid}/layers").json()}
    assert layers[couch["layer"]]["kind"] == "furniture" and layers[cam["layer"]]["kind"] == "cctv"
    cctv = cam["layer"]
    # the CCTV layer takes only CCTV equipment
    r = c.post(base, json={"id": "c2", "floor": fid, "item": "doc.couch", "at": [2, 2], "layer": cctv})
    assert r.status_code == 400 and "не принимает" in r.json()["detail"]
    assert c.post(base, json={"floor": fid, "item": "doc.couch", "at": [2, 2], "layer": "nope"}).status_code == 400
    # polylines are not furniture; no layer kind takes free polylines yet
    r = c.post(base, json={"floor": fid, "geom": "polyline", "points": [[0, 0], [1, 1]], "layer": couch["layer"]})
    assert r.status_code == 400
    assert c.post(base, json={"floor": fid, "geom": "polyline", "points": [[0, 0], [1, 1]]}).status_code == 400
    # a second furniture layer: objects move between layers of a kind that accepts them
    b = c.post(f"/api/projects/{pid}/layers", json={"kind": "furniture", "name": "Вариант Б"}).json()
    moved = c.patch(f"{base}/couch", json={"layer": b["id"], "version": couch["version"]}).json()
    assert moved["layer"] == b["id"] and moved["version"] == couch["version"] + 1
    items = c.get(f"{base}?layer={b['id']}").json()["items"]
    assert [x["id"] for x in items] == ["couch"]
    # a locked layer: its objects cannot be changed or deleted, nor can the layer
    c.patch(f"/api/projects/{pid}/layers/{b['id']}", json={"locked": True})
    r = c.patch(f"{base}/couch", json={"at": [5, 5], "version": moved["version"]})
    assert r.status_code == 400 and "заблокирован" in r.json()["detail"]
    assert c.delete(f"{base}/couch?version={moved['version']}").status_code == 400
    assert c.delete(f"/api/projects/{pid}/layers/{b['id']}").status_code == 409
    c.patch(f"/api/projects/{pid}/layers/{b['id']}", json={"locked": False})
    # deleting a layer deletes its objects
    assert c.delete(f"/api/projects/{pid}/layers/{b['id']}").status_code == 204
    assert "couch" not in {x["id"] for x in c.get(base).json()["items"]}
    log = c.get(f"/api/projects/{pid}/audit").json()
    assert {("layer", "create"), ("layer", "update"), ("layer", "delete"), ("object", "create")} <= \
        {(x["entity"], x["action"]) for x in log}


def test_rooms_keep_ids_and_objects_know_their_room(c, built):
    pid, d = built
    did = d["id"]
    rooms = c.get(f"/api/drawings/{did}/rooms").json()
    assert rooms and all(r["idx"] is not None and r["floor"] for r in rooms)
    fl = d["result"]["floors"][0]
    meta = [r for r in fl["rooms"] if r.get("id")]
    assert meta and {r["id"] for r in meta} <= {r["id"] for r in rooms}
    # a point inside a room (its label position in plan coordinates, from the plan)
    plan = c.get(f"/api/drawings/{did}/files/{fl['plan']}").json()
    k, room = max(enumerate(plan["rooms"]), key=lambda kr: kr[1]["area"])
    rid = next(r["id"] for r in rooms if r["floor"] == fl["id"] and r["idx"] == k)
    obj = c.post(f"/api/drawings/{did}/objects", json={"id": "inroom", "floor": fl["id"], "item": "doc.desk",
                                                       "at": room["label"]}).json()
    assert obj["room"] == rid
    far = c.post(f"/api/drawings/{did}/objects", json={"id": "far", "floor": fl["id"], "item": "doc.desk",
                                                       "at": [-500, -500]}).json()
    assert far["room"] is None
    # a rebuild keeps room ids and the object's room
    c.post(f"/api/drawings/{did}/rebuild", json={"geometry": {"snap_tolerance": 0.011}})
    d2 = _wait(c, did)
    assert d2["build"] == d["build"] + 1
    rooms2 = c.get(f"/api/drawings/{did}/rooms").json()
    assert {r["id"] for r in rooms2 if r["idx"] is not None} == {r["id"] for r in rooms}
    objs = {x["id"]: x for x in c.get(f"/api/drawings/{did}/objects").json()["items"]}
    assert objs["inroom"]["room"] == rid

    # the specification room by room
    rep = c.get(f"/api/reports/equipment?project={pid}&by=room").json()
    names = {(g["room"], x["item"]) for g in rep["rooms"] for x in g["items"]}
    assert (room["name"] or "без названия", "doc.desk") in names and ("вне помещений", "doc.desk") in names
    assert c.get("/api/reports/equipment?by=room").status_code == 400
    x = c.get(f"/api/reports/equipment?project={pid}&by=room&format=xlsx")
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    assert "по помещениям" in ws["A1"].value
    cctv = next(x for x in c.get(f"/api/projects/{pid}/layers").json() if x["kind"] == "cctv")
    rep = c.get(f"/api/reports/equipment?project={pid}&layer={cctv['id']}").json()
    assert {r["item"] for r in rep["rows"]} == {"sec.dome"} and rep["layer"]["name"] == cctv["name"]


def test_rooms_backfill(c, built, pg):
    """Drawings built before rooms had rows get them from the stored plans."""
    from sqlalchemy import delete

    from dwg3d import db, rooms
    from dwg3d.models import Build, Room

    pid, d = built
    did = d["id"]
    with db.session() as s:
        b = s.get(Build, (did, c.get(f"/api/drawings/{did}").json()["build"]))
        ids_before = {r["id"] for f in b.result["floors"] for r in f["rooms"] if r.get("id")}
        s.execute(delete(Room).where(Room.drawing_id == did))
        for f in b.result["floors"]:
            for r in f["rooms"]:
                r.pop("id", None)
    with db.session() as s:
        n = rooms.backfill(s, did)
    assert n == len(ids_before)
    d2 = c.get(f"/api/drawings/{did}").json()
    assert all(r.get("id") for f in d2["result"]["floors"] for r in f["rooms"])


def test_variants_copy_and_compare(c, built):
    pid, d = built
    did, fid = d["id"], d["result"]["floors"][0]["id"]
    base = f"/api/drawings/{did}/objects"
    a = c.post(f"/api/projects/{pid}/layers", json={"kind": "furniture", "name": "Расстановка"}).json()
    ops = [{"op": "create", "id": f"v{k}", "floor": fid, "item": "doc.chair", "at": [1 + k, 1], "layer": a["id"]}
           for k in range(3)]
    ops.append({"op": "create", "id": "vd", "floor": fid, "item": "doc.desk", "at": [5, 5], "layer": a["id"]})
    assert c.post(f"{base}:batch", json={"ops": ops}).status_code == 200
    b = c.post(f"/api/projects/{pid}/layers/{a['id']}/copy", json={})
    assert b.status_code == 201
    b = b.json()
    assert b["kind"] == "furniture" and b["count"] == 4 and b["name"] == "Расстановка — вариант 2"
    assert b["props"]["variant_group"] == a["id"]
    got = {x["id"]: x for x in c.get(f"/api/projects/{pid}/layers").json()}
    assert got[a["id"]]["props"]["variant_group"] == a["id"]
    items_b = [x for x in c.get(f"{base}?layer={b['id']}").json()["items"]]
    assert {x["props"]["origin"] for x in items_b} == {"v0", "v1", "v2", "vd"}
    assert not {x["id"] for x in items_b} & {"v0", "v1", "v2", "vd"}
    same = c.get(f"/api/projects/{pid}/layers/compare?a={a['id']}&b={b['id']}").json()
    assert same["counts"] == {"added": 0, "removed": 0, "moved": 0, "changed": 0, "same": 4} and not same["objects"]
    # in variant B: one chair moved, the desk replaced by a couch, one chair removed, a cabinet added
    by_origin = {x["props"]["origin"]: x for x in items_b}
    ops = [{"op": "update", "id": by_origin["v0"]["id"], "version": 1, "at": [10, 1]},
           {"op": "update", "id": by_origin["vd"]["id"], "version": 1, "item": "doc.couch"},
           {"op": "delete", "id": by_origin["v2"]["id"], "version": 1},
           {"op": "create", "id": "vn", "floor": fid, "item": "st.cabinet", "at": [2, 8], "layer": b["id"]}]
    assert c.post(f"{base}:batch", json={"ops": ops}).status_code == 200
    cmp = c.get(f"/api/projects/{pid}/layers/compare?a={a['id']}&b={b['id']}").json()
    assert cmp["counts"] == {"added": 1, "removed": 1, "moved": 1, "changed": 1, "same": 1}
    ch = {o["key"]: o for o in cmp["objects"]}
    assert ch["v0"]["change"] == "moved" and ch["v0"]["from"]["at"] == [1.0, 1.0] and ch["v0"]["at"] == [10.0, 1.0]
    assert ch["vd"]["change"] == "changed" and "предмет" in ch["vd"]["what"]
    assert ch["v2"]["change"] == "removed" and ch["vn"]["change"] == "added"
    spec = {r["item"]: r for r in cmp["items"]}
    assert (spec["doc.chair"]["qty_a"], spec["doc.chair"]["qty_b"], spec["doc.chair"]["delta"]) == (3, 2, -1)
    assert spec["st.cabinet"]["delta"] == 1 and spec["doc.desk"]["delta"] == -1
    # a copy of a copy stays in the group, its objects keep the first origin
    c3 = c.post(f"/api/projects/{pid}/layers/{b['id']}/copy", json={"name": "Эконом"}).json()
    assert c3["name"] == "Эконом" and c3["props"]["variant_group"] == a["id"]
    cmp = c.get(f"/api/projects/{pid}/layers/compare?a={a['id']}&b={c3['id']}").json()
    assert cmp["counts"]["same"] == 1 and cmp["counts"]["moved"] == 1
    assert c.get(f"/api/projects/{pid}/layers/compare?a={a['id']}&b=nope").status_code == 404


def test_drawing_export_with_layers(c, built):
    """Objects of project layers drawn into the DXF: blocks with attributes,
    camera views, routes, zones; at the right place of the source drawing."""
    import ezdxf

    from dwg3d.units import UNIT_SCALE

    pid, d = built
    did = d["id"]
    fl = d["result"]["floors"][0]
    s = UNIT_SCALE[d["result"]["units"]]
    ox, oy = fl.get("offset") or (0.0, 0.0)
    base = f"/api/drawings/{did}/objects"
    lay = c.post(f"/api/projects/{pid}/layers", json={"kind": "furniture", "name": "Экспорт: мебель"}).json()
    routes = c.post(f"/api/projects/{pid}/layers", json={"kind": "routes", "name": "Экспорт: маршруты"}).json()
    zones = c.post(f"/api/projects/{pid}/layers", json={"kind": "zones", "name": "Экспорт: зоны"}).json()
    ops = [{"op": "create", "id": "ex1", "floor": fl["id"], "item": "doc.couch", "at": [3, 4], "angle": 90,
            "note": "KS-1", "layer": lay["id"]},
           {"op": "create", "id": "ex2", "floor": fl["id"], "item": "sec.dome", "at": [5, 5], "fov": 90, "range": 6},
           {"op": "create", "id": "ex3", "geom": "route", "layer": routes["id"], "props": {
               "flow": "dirty", "name": "Отходы", "stops": [{"floor": fl["id"], "at": [1, 1], "label": "А"},
                                                             {"floor": fl["id"], "at": [6, 1], "label": "Б"}],
               "path": [{"floor": fl["id"], "pts": [[1, 1], [6, 1]]}], "length": 5, "time": 4, "build": d["build"]}},
           {"op": "create", "id": "ex4", "geom": "polygon", "layer": zones["id"], "floor": fl["id"],
            "points": [[0, 0], [2, 0], [2, 2], [0, 2]], "props": {"zone": "clean", "name": "Чистая"}}]
    r = c.post(f"{base}:batch", json={"ops": ops})
    assert r.status_code == 200, r.text
    x = c.get(f"/api/drawings/{did}/drawing.dxf")
    assert x.status_code == 200 and "_слои" in __import__("urllib.parse").parse.unquote(x.headers["content-disposition"])
    doc = ezdxf.read(__import__("io").StringIO(x.content.decode("utf-8", "replace")))
    msp = doc.modelspace()
    assert {"3D_Экспорт_ мебель", "3D_Экспорт_ маршруты", "3D_Экспорт_ зоны"} <= {ly.dxf.name for ly in doc.layers}
    couch = next(e for e in msp.query("INSERT") if e.dxf.name == "3D_doc.couch" and e.dxf.layer == "3D_Экспорт_ мебель")
    assert couch.dxf.rotation == 90
    assert abs(couch.dxf.insert.x * s + ox - 3) < 1e-6 and abs(couch.dxf.insert.y * s + oy - 4) < 1e-6
    attrs = {a.dxf.tag: a.dxf.text for a in couch.attribs}
    assert attrs["NOTE"] == "KS-1" and attrs["NAME"]
    assert any(e.dxf.name == "3D_sec.dome" for e in msp.query("INSERT"))
    assert any(abs(a.dxf.radius * s - 6) < 1e-6 for a in msp.query("ARC"))           # the camera view
    assert msp.query(f'LWPOLYLINE[layer=="3D_Экспорт_ маршруты"]') and msp.query("HATCH")
    # only some layers / none
    only = c.get(f"/api/drawings/{did}/drawing.dxf?layers={zones['id']}")
    assert only.status_code == 200 and b"3D_doc.couch" not in only.content
    assert c.get(f"/api/drawings/{did}/drawing.dxf?layers=none").status_code == 400   # no edits either
