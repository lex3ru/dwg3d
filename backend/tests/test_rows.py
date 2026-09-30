"""Furniture and pins as rows: versions, conflicts, batches, audit, rebuild moves."""
import json
import uuid

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from dwg3d import db, store, viewdata
from dwg3d.models import Build, Project


def _floor(fid, bbox, offset=(0.0, 0.0), elevation=0.0, name=None):
    return {"id": fid, "space": "Model", "owner": None, "bbox": list(bbox), "offset": list(offset),
            "elevation": elevation, "name": name or fid, "level": 1, "height": 3.0}


A, B = (0, 0, 30, 20), (100, 0, 130, 20)


def _project(floors, center=(0.0, 0.0)) -> str:
    """A project with one finished build of the given floors (no files, no job)."""
    pid = uuid.uuid4().hex[:12]
    result = {"center": list(center), "floors": floors}
    with db.session() as s:
        s.add(Project(id=pid, filename="p.dxf", input_path="input.dxf", current_build=1))
        s.flush()
        s.add(Build(project_id=pid, n=1, result=result, config={}, out_dir="out"))
        store.sync_floors(s, pid, result)
    return pid


def _rebuild(pid, floors, center=(0.0, 0.0)) -> list[str]:
    with db.session() as s:
        p = store.get_project(s, pid, lock=True)
        old = store.current_build(s, p)
        result = {"center": list(center), "floors": floors}
        warns = store.sync_floors(s, pid, result, old.result)
        s.add(Build(project_id=pid, n=p.current_build + 1, result=result, config={}, out_dir="out"))
        s.flush()
        p.current_build += 1
    return warns


def _view(pid):
    with db.session() as s:
        return viewdata.view_data(s, pid)


def _apply(pid, entity, ops, **kw):
    with db.session() as s:
        return viewdata.apply(s, pid, entity, ops, **kw)


# ------------------------------------------------------- rebuild moves ---
def test_rows_follow_swapped_ids_and_changed_offset(pg):
    pid = _project([_floor("c0", A, name="1 этаж"), _floor("c1", B, elevation=3.0, name="2 этаж")], center=(10.0, 5.0))
    _apply(pid, "placement", [{"op": "create", "id": "f1", "floor": "c0", "item": "doc.couch", "at": [5, 5]},
                              {"op": "create", "id": "f2", "floor": "c1", "item": "diag.mri", "at": [8, 2], "angle": 90}])
    _apply(pid, "pin", [{"op": "create", "id": "m1", "kind": "marker", "floor": "c1", "pos": [1.0, 3.1, -2.0]},
                        {"op": "create", "id": "m2", "kind": "comment", "floor": "", "pos": [0.0, 0.0, 0.0], "text": "x"}])
    # the next build detects the sheets in the other order and re-aligns the second one
    warns = _rebuild(pid, [_floor("c0", B, offset=(0.5, -1.0), elevation=3.3), _floor("c1", A)], center=(12.0, 5.0))
    v = _view(pid)
    f = {it["id"]: it for it in v["furniture"]}
    assert f["f1"]["floor"] == "c1" and f["f1"]["at"] == [5.0, 5.0]
    assert f["f2"]["floor"] == "c0" and f["f2"]["at"] == [8.5, 1.0]
    m = {p["id"]: p for p in v["markers"] + v["comments"]}
    # plan (1 + 10, 2 + 5) shifted by (0.5, -1) -> (11.5, 6); new centre (12, 5)
    assert m["m1"]["floor"] == "c0" and m["m1"]["pos"] == pytest.approx([-0.5, 3.4, -1.0])
    assert m["m2"]["floor"] == "" and m["m2"]["pos"] == pytest.approx([-2.0, 0.0, 0.0])     # centre only
    assert not warns and all(it["version"] == 1 for it in f.values())       # moves are not user edits


def test_lost_floor_is_kept_aside_and_restored_later(pg):
    pid = _project([_floor("c0", A), _floor("c1", B, name="Подвал")])
    _apply(pid, "placement", [{"op": "create", "id": "f1", "floor": "c1", "item": "st.cabinet", "at": [101, 1]}])
    warns = _rebuild(pid, [_floor("c0", A)])
    v = _view(pid)
    assert "furniture" not in v and v["furniture_unplaced"][0]["id"] == "f1"
    assert v["furniture_unplaced"][0]["_anchor"] == {"name": "Подвал"}
    assert warns and "Подвал" in warns[0]
    # the sheet comes back (as c5, shifted): the item returns to it
    warns = _rebuild(pid, [_floor("c0", A), _floor("c5", B, offset=(2.0, 0.0))])
    v = _view(pid)
    assert "furniture_unplaced" not in v and not warns
    assert v["furniture"][0]["floor"] == "c5" and v["furniture"][0]["at"] == [103.0, 1.0]


def test_unplaced_item_put_back_on_a_floor(pg):
    pid = _project([_floor("c0", A), _floor("c1", B, name="Подвал")])
    _apply(pid, "placement", [{"op": "create", "id": "f1", "floor": "c1", "item": "st.cabinet", "at": [101, 1]}])
    _rebuild(pid, [_floor("c0", A)])
    u = _view(pid)["furniture_unplaced"][0]
    r = _apply(pid, "placement", [{"op": "update", "id": "f1", "version": u["version"], "floor": "c0"}], build=2)
    assert r["items"][0]["floor"] == "c0" and "_anchor" not in r["items"][0]


# ------------------------------------------------ versions and conflicts ---
@pytest.fixture(scope="module")
def api(pg):
    from dwg3d import api as module
    return TestClient(module.app)


def test_row_api_versions_conflicts_batch_audit(pg, api):
    pid = _project([_floor("c0", A), _floor("c1", B)])
    base = f"/api/projects/{pid}/placements"
    r = api.post(base, json={"id": "a", "floor": "c0", "item": "doc.couch", "at": [1, 2], "build": 1})
    assert r.status_code == 201 and r.json()["version"] == 1
    assert api.post(base, json={"id": "a", "floor": "c0", "item": "doc.couch", "at": [1, 2]}).status_code == 409
    assert api.post(base, json={"floor": "c9", "item": "doc.couch", "at": [1, 2]}).status_code == 400
    assert api.post(base, json={"floor": "c0", "item": "nope", "at": [1, 2]}).status_code == 400
    assert api.post(base, json={"floor": "c0", "item": "doc.couch", "at": [1, 2], "build": 7}).status_code == 409

    # window 1 moves the couch; window 2, still on version 1, tries to turn it
    r = api.patch(f"{base}/a", json={"version": 1, "at": [3, 4]})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["at"] == [3, 4]
    r = api.patch(f"{base}/a", json={"version": 1, "angle": 90})
    assert r.status_code == 409
    [conflict] = r.json()["conflicts"]
    assert conflict["id"] == "a" and conflict["current"]["at"] == [3, 4] and conflict["current"]["version"] == 2
    assert api.patch(f"{base}/a", json={"version": 2, "angle": 90}).json()["angle"] == 90
    # the same values again: no new version
    assert api.patch(f"{base}/a", json={"version": 3, "angle": 90}).json()["version"] == 3

    # window 2 adds its own items meanwhile: nothing of window 1 is lost
    r = api.post(f"{base}:batch", json={"build": 1, "ops": [
        {"op": "create", "id": "b", "floor": "c1", "item": "diag.ct", "at": [101, 1]},
        {"op": "create", "id": "c", "floor": "c1", "item": "diag.ct", "at": [105, 1]}]})
    assert r.status_code == 200 and {it["id"] for it in r.json()["items"]} == {"b", "c"}
    listed = api.get(base, params={"floor": "c1"}).json()
    assert listed["build"] == 1 and {it["id"] for it in listed["items"]} == {"b", "c"}
    assert len(api.get(base).json()["items"]) == 3

    # a batch with one stale op writes nothing
    r = api.post(f"{base}:batch", json={"ops": [{"op": "delete", "id": "b", "version": 1},
                                                {"op": "update", "id": "a", "version": 1, "angle": 0}]})
    assert r.status_code == 409 and [c["id"] for c in r.json()["conflicts"]] == ["a"]
    assert len(api.get(base).json()["items"]) == 3
    # deleting: stale version refused, missing row is fine (already deleted)
    assert api.delete(f"{base}/b", params={"version": 5}).status_code == 409
    assert api.delete(f"{base}/b", params={"version": 1}).status_code == 204
    assert api.delete(f"{base}/b", params={"version": 1}).status_code == 204
    # updating a row someone deleted: 409 with current = null
    r = api.patch(f"{base}/b", json={"version": 1, "angle": 5})
    assert r.status_code == 409 and r.json()["conflicts"] == [{"id": "b", "current": None}]

    # pins the same way
    pins = f"/api/projects/{pid}/pins"
    r = api.post(pins, json={"id": "k", "kind": "comment", "floor": "c0", "pos": [1, 2, 3], "text": "Трещина"})
    assert r.status_code == 201 and r.json()["text"] == "Трещина"
    assert api.post(pins, json={"kind": "flag", "pos": [1, 2, 3]}).status_code == 400
    assert api.patch(f"{pins}/k", json={"version": 1, "text": "Скол"}).json()["version"] == 2
    assert api.get(pins).json()["comments"][0]["text"] == "Скол"

    log = api.get(f"/api/projects/{pid}/audit").json()
    acts = [(a["entity"], a["entity_id"], a["action"]) for a in reversed(log)]
    assert acts[:4] == [("placement", "a", "create"), ("placement", "a", "update"),
                        ("placement", "a", "update"), ("placement", "b", "create")]
    assert ("placement", "b", "delete") in acts and ("pin", "k", "update") in acts
    upd = next(a for a in log if a["entity_id"] == "a" and a["action"] == "update" and a["after"]["angle"] == 90)
    assert upd["before"]["angle"] == 0 and "version" not in upd["after"]
    assert api.get("/api/projects/nope/placements").status_code == 404


def test_legacy_put_view_keeps_unplaced_and_other_kinds(pg, api):
    pid = _project([_floor("c0", A), _floor("c1", B, name="Подвал")])
    _apply(pid, "placement", [{"op": "create", "id": "u", "floor": "c1", "item": "st.cabinet", "at": [101, 1]}])
    _rebuild(pid, [_floor("c0", A)])
    _apply(pid, "pin", [{"op": "create", "id": "m", "kind": "marker", "pos": [0, 0, 0]}])
    with db.session() as s:
        s.execute(text("UPDATE jobs SET status = 'done' WHERE project_id = :p"), {"p": pid})
    v = api.put(f"/api/jobs/{pid}/view", json={"furniture": [{"id": "a", "floor": "c0", "item": "doc.couch", "at": [1, 1]}],
                                               "comments": []}).json()
    assert [it["id"] for it in v["furniture"]] == ["a"] and v["furniture_unplaced"][0]["id"] == "u"
    assert v["markers"][0]["id"] == "m"
    v = api.put(f"/api/jobs/{pid}/view", json={"furniture_unplaced": []}).json()
    assert "furniture_unplaced" not in v and v["furniture"][0]["id"] == "a"


# ------------------------------------------------ migration 0003 (data) ---
def test_migration_moves_view_json_to_rows(pg):
    name = f"dwg3d_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(pg.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    eng = create_engine(pg.set(database=name))
    try:
        cfg = db.alembic_config()
        with eng.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0002")
            conn.commit()
            anchor = {"id": "c7", "space": "Model", "owner": None, "bbox": [0, 0, 1, 1], "name": "Подвал", "offset": [0, 0]}
            view = {"name": "x", "furniture": [{"id": "a", "floor": "c0", "item": "doc.couch", "at": [1, 2], "angle": 90,
                                                "size": [1, 2, 3]}],
                    "furniture_unplaced": [{"id": "b", "floor": "c7", "item": "diag.ct", "at": [5, 5], "angle": 0,
                                            "_anchor": anchor}],
                    "markers": [{"id": "m", "floor": "c0", "pos": [1, 2, 3], "text": "", "label": "A", "created": 1.7e9}],
                    "comments": [{"id": "k", "floor": "", "pos": [0, 0, 0], "text": "!"}]}
            conn.execute(text("INSERT INTO projects (id, filename, input_path, view, current_build) "
                              "VALUES ('p1', 'p.dxf', 'input.dxf', CAST(:v AS jsonb), 1)"), {"v": json.dumps(view)})
            conn.execute(text("INSERT INTO floors (project_id, anchor, candidate, name) "
                              "VALUES ('p1', '{}'::jsonb, 'c0', '1 этаж')"))
            conn.commit()
            command.upgrade(cfg, "head")
            conn.commit()
        with eng.connect() as conn:
            rows = conn.execute(text("SELECT p.id, f.candidate, f.name, p.size, p.angle FROM placements p "
                                     "LEFT JOIN floors f ON f.id = p.floor_id ORDER BY p.id")).all()
            assert rows == [("a", "c0", "1 этаж", [1.0, 2.0, 3.0], 90.0), ("b", None, "Подвал", None, 0.0)]
            pins = conn.execute(text("SELECT id, kind, floor_id IS NULL, label, extract(epoch FROM created_at) > 1e9 "
                                     "FROM pins ORDER BY id")).all()
            assert pins == [("k", "comment", True, "", True), ("m", "marker", False, "A", True)]
            cols = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns "
                                                    "WHERE table_name = 'projects'"))}
            assert "view" not in cols
    finally:
        eng.dispose()
        with admin.connect() as c:
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()

