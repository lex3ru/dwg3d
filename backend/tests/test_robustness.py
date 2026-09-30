"""Edit re-anchoring, plausibility checks, caching, config validation, API."""
import copy
import importlib
import time

import pytest

from dwg3d.config import ConfigError, load_config, validate_config
from dwg3d.pipeline import render_debug, run

from make_sample import make

NO_EXPORT = {"export": {"ifc": False, "obj": False}}


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make(tmp_path_factory.mktemp("dxf") / "sample.dxf")


def _edits(fid):
    return {fid: {
        "openings": [{"at": [8.0, 0.15], "kind": "vitrage"}],
        "add_walls": [{"a": [5.12, 5.0], "b": [11.7, 5.0], "thickness": 0.1}],
        "rooms": [{"at": [2.0, 5.0], "name": "Холл"}],
    }}


@pytest.fixture(scope="module")
def edited(sample, tmp_path_factory):
    base = run(sample, tmp_path_factory.mktemp("base"), NO_EXPORT, debug_png=False, use_cache=False)
    fid = base["floors"][0]["id"]
    meta = run(sample, tmp_path_factory.mktemp("ed"), {**NO_EXPORT, "edits": _edits(fid)},
               debug_png=False, use_cache=False)
    return base, meta, fid


def _stats(meta, fid):
    f = next(f for f in meta["floors"] if f["id"] == fid)
    return f["stats"]["openings"], f["stats"]["rooms"], sorted(r["name"] for r in f["rooms"])


# ------------------------------------------------------------- anchoring ---
def test_stored_edits_carry_anchor(edited):
    _, meta, fid = edited
    stored = meta["config"]["edits"][fid]
    assert stored["_anchor"]["id"] == fid and len(stored["_anchor"]["bbox"]) == 4
    assert meta["config"]["edits_unmatched"] == []


def test_edits_follow_renumbered_floor_and_changed_alignment(sample, edited, tmp_path):
    _, meta, fid = edited
    e = copy.deepcopy(meta["config"]["edits"][fid])
    # as if made when the floor was called "c7" and aligned 5 m further east:
    # coordinates and the recorded offset both carry the old +5 m shift
    e["_anchor"]["offset"][0] += 5.0
    for k in ("openings", "add_walls", "rooms"):
        for it in e[k]:
            for p in ("a", "b", "at"):
                if p in it:
                    it[p][0] += 5.0
    again = run(sample, tmp_path, {**NO_EXPORT, "edits": {"c7": e}}, debug_png=False, use_cache=False)
    assert _stats(again, fid) == _stats(meta, fid)
    assert list(again["config"]["edits"]) == [fid]
    assert again["config"]["edits"][fid]["add_walls"][0]["a"] == pytest.approx([5.12, 5.0])


def test_edits_of_a_vanished_sheet_are_kept_aside(sample, edited, tmp_path):
    base, meta, fid = edited
    e = copy.deepcopy(meta["config"]["edits"][fid])
    e["_anchor"]["bbox"] = [1000, 1000, 1010, 1010]
    again = run(sample, tmp_path, {**NO_EXPORT, "edits": {fid: e}}, debug_png=False, use_cache=False)
    assert _stats(again, fid) == _stats(base, fid)            # not applied anywhere
    assert again["edits_unmatched"] == 1
    assert again["config"]["edits_unmatched"][0]["key"] == fid
    assert any("не применены" in w for w in again["warnings"])


def test_legacy_edits_without_anchor_still_apply(sample, edited, tmp_path):
    _, meta, fid = edited
    again = run(sample, tmp_path, {**NO_EXPORT, "edits": _edits(fid)}, debug_png=False, use_cache=False)
    assert _stats(again, fid) == _stats(meta, fid)


# ---------------------------------------------------------------- quality ---
def test_quality_ok_on_sample(edited):
    base, _, _ = edited
    assert base["quality"] == {"status": "ok", "issues": []}


def test_quality_flags_wrong_units(sample, tmp_path):
    meta = run(sample, tmp_path, {**NO_EXPORT, "units": "m"}, debug_png=False, use_cache=False)
    assert meta["quality"]["status"] == "suspect" and meta["quality"]["issues"]


# ------------------------------------------------------------------ cache ---
def test_rebuild_reuses_cached_floors(sample, tmp_path):
    first = run(sample, tmp_path, NO_EXPORT, debug_png=False)
    assert first["cache"]["floors_reused"] == 0
    fid = first["floors"][0]["id"]
    t = time.time()
    second = run(sample, tmp_path, NO_EXPORT, debug_png=False)
    assert second["cache"]["floors_reused"] == 2
    assert [f["stats"] for f in second["floors"]] == [f["stats"] for f in first["floors"]]
    third = run(sample, tmp_path, {**NO_EXPORT, "edits": _edits(fid)}, debug_png=False)
    assert third["cache"]["floors_reused"] == 1                 # only the edited floor rebuilt
    assert time.time() - t < 60
    assert len(list((tmp_path / "cache").glob("plan_*.pkl"))) == 2   # stale plans pruned
    assert render_debug(tmp_path, f"floor_{fid}.png").is_file()
    assert render_debug(tmp_path, "overlay.png").is_file()
    assert render_debug(tmp_path, "floor_nope.png") is None


# ------------------------------------------------------------- validation ---
@pytest.mark.parametrize("bad", [
    {"geometry": {"max_wall_thickness": 1e6}},
    {"no_such_key": 1},
    {"units": "parsec"},
    {"building": {"roof": "yes"}},
    {"geometry": {"stair_tread": [0.2]}},
    {"edits": {"c0": {"add_walls": [{"a": [0, "x"], "b": [1, 1]}]}}},
    {"edits": {"c0": {"drop_tables": []}}},
    {"floors": {"items": [{"candidate": "c0", "height": 1e9}]}},
])
def test_validate_config_rejects(bad):
    with pytest.raises(ConfigError):
        validate_config(load_config(bad))


def test_validate_config_accepts_defaults_and_edits(edited):
    validate_config(load_config())
    _, meta, _ = edited
    validate_config(load_config(meta["config"]))


# -------------------------------------------------------------------- API ---
@pytest.fixture(scope="module")
def client(tmp_path_factory, sample):
    import os
    from fastapi.testclient import TestClient

    os.environ["DWG3D_DATA"] = str(tmp_path_factory.mktemp("data"))
    import dwg3d.api
    api = importlib.reload(dwg3d.api)
    return TestClient(api.app), api


def _wait(c, jid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.2)
    raise TimeoutError


def test_api_flow(client, sample):
    c, api = client
    r = c.post("/api/jobs", files={"file": ("plan.dxf", sample.read_bytes())},
               data={"config": '{"geometry": {"snap_tolerance": 99}}'})
    assert r.status_code == 400
    r = c.post("/api/jobs", files={"file": ("plan.dxf", sample.read_bytes())})
    jid = r.json()["id"]
    j = _wait(c, jid)
    assert j["status"] == "done" and "trace" not in j and "input" not in j
    assert j["result"]["quality"]["status"] == "ok"
    fid = j["result"]["floors"][0]["id"]

    assert c.post(f"/api/jobs/{jid}/rebuild", json={"geometry": {"min_room_area": -1}}).status_code == 400
    r = c.post(f"/api/jobs/{jid}/rebuild", json={"edits": _edits(fid)})
    assert r.status_code == 200
    assert c.post(f"/api/jobs/{jid}/rebuild", json={}).status_code == 409   # still queued/running
    j = _wait(c, jid)
    assert j["status"] == "done" and j["build"] == 2
    anchor = j["config"]["edits"][fid]["_anchor"]
    assert anchor["id"] == fid
    # debug PNGs are rendered on demand
    r = c.get(f"/api/jobs/{jid}/files/debug/floor_{fid}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert c.get(f"/api/jobs/{jid}/files/debug/../../job.json").status_code == 404


def test_api_error_hides_trace(client):
    c, _ = client
    r = c.post("/api/jobs", files={"file": ("broken.dxf", b"0\nSECTION\n2\nGARBAGE\n")})
    j = _wait(c, r.json()["id"])
    assert j["status"] == "error" and j["error"] and "trace" not in j


def test_api_view_settings_and_detail_model(client, sample):
    c, api = client
    jid = c.post("/api/jobs", files={"file": ("plan.dxf", sample.read_bytes())}).json()["id"]
    j = _wait(c, jid)
    assert j["result"]["room_types"] and "entrances" in j["result"]
    assert any(x["id"] == jid for x in c.get("/api/jobs").json())
    r = c.put(f"/api/jobs/{jid}/view", json={"site": {"lat": 55.75, "lon": 37.62, "azimuth": 15, "scale": 1},
                                            "comments": [{"id": "k1", "floor": "c1", "pos": [1, 2, 3], "text": "Трещина"}]})
    assert r.status_code == 200 and r.json()["site"]["azimuth"] == 15
    assert c.put(f"/api/jobs/{jid}/view", json={"site": {"lat": 120, "lon": 0}}).status_code == 400
    assert c.put(f"/api/jobs/{jid}/view", json={"comments": [{"pos": [1, 2]}]}).status_code == 400
    v = c.get(f"/api/jobs/{jid}/view").json()
    assert v["comments"][0]["text"] == "Трещина" and v["site"]["lat"] == 55.75
    # furniture: plan position, angle normalised, other view keys kept
    v = c.put(f"/api/jobs/{jid}/view", json={"furniture": [
        {"id": "a1", "floor": "c1", "item": "med.couch", "at": [2.5, 3], "angle": -90, "size": [0.7, 1.9, 0.75]}]}).json()
    assert v["furniture"][0]["angle"] == 270 and v["furniture"][0]["size"] == [0.7, 1.9, 0.75]
    assert v["comments"][0]["text"] == "Трещина"
    v = c.put(f"/api/jobs/{jid}/view", json={"furniture": [
        {"id": "k1", "item": "sec.dome", "at": [1, 1], "elev": 2.8, "fov": 110, "range": 12}]}).json()
    assert v["furniture"][0]["fov"] == 110 and v["furniture"][0]["elev"] == 2.8
    assert c.put(f"/api/jobs/{jid}/view", json={"furniture": [{"item": "x", "at": [1, 2], "fov": 400}]}).status_code == 400
    assert c.put(f"/api/jobs/{jid}/view", json={"furniture": [{"item": "x", "at": [1]}]}).status_code == 400
    # written against another build: refused, nothing lost silently
    r = c.put(f"/api/jobs/{jid}/view", json={"furniture": [], "_build": j["build"] + 5})
    assert r.status_code == 409
    assert c.get(f"/api/jobs/{jid}/view").json()["furniture"][0]["id"] == "k1"
    assert c.put(f"/api/jobs/{jid}/view", json={"furniture": [], "_build": j["build"]}).status_code == 200
    assert c.put(f"/api/jobs/{jid}/view", json={"furniture": [{"item": "x", "at": [1, 2], "size": [0, 1, 1]}]}).status_code == 400
    # detail model: only GLB is accepted
    assert c.post(f"/api/jobs/{jid}/detail", files={"file": ("x.glb", b"not a glb at all")}).status_code == 400
    glb = (api._job_dir(jid) / "out" / "model.glb").read_bytes()
    v = c.post(f"/api/jobs/{jid}/detail", files={"file": ("facade.glb", glb)}).json()
    assert v["detail"]["file"] == "facade.glb" and v["detail"]["version"] == 1
    assert c.get(f"/api/jobs/{jid}/detail.glb").content == glb
    v = c.put(f"/api/jobs/{jid}/view", json={"detail": {"offset": [1, 0, 2], "rotation": 90}}).json()
    assert v["detail"]["file"] == "facade.glb" and v["detail"]["rotation"] == 90
    assert c.delete(f"/api/jobs/{jid}/detail").json().get("detail") is None
    assert c.get(f"/api/jobs/{jid}/detail.glb").status_code == 404


def test_api_furniture_survives_rebuild(client, sample):
    c, _ = client
    jid = c.post("/api/jobs", files={"file": ("plan.dxf", sample.read_bytes())}).json()["id"]
    j = _wait(c, jid)
    fids = [f["id"] for f in j["result"]["floors"]]
    items = [{"id": f"i{k}", "floor": fid, "item": "doc.couch", "at": [1.0 + k, 2.0], "angle": 0} for k, fid in enumerate(fids)]
    assert c.put(f"/api/jobs/{jid}/view", json={"furniture": items, "_build": j["build"]}).status_code == 200
    assert c.post(f"/api/jobs/{jid}/rebuild", json={"geometry": {"snap_tolerance": 0.011}}).status_code == 200
    # while the model is rebuilt, floor-bound data is not accepted
    r = c.put(f"/api/jobs/{jid}/view", json={"furniture": []})
    assert r.status_code in (200, 409)
    j2 = _wait(c, jid)
    v = c.get(f"/api/jobs/{jid}/view").json()
    new_ids = {f["id"] for f in j2["result"]["floors"]}
    if r.status_code == 409:
        assert len(v["furniture"]) == len(items)
    assert all(it["floor"] in new_ids for it in v.get("furniture") or [])
    assert "furniture_unplaced" not in v
