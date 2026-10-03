"""Routes on the server: the walkability grid, the way through a door, plan_route, flow checks."""
import json

import pytest
from sqlalchemy import text

from dwg3d import db, planning, routing
from test_agent_tools import Tools, world  # noqa: F401  (fixture)
from test_auth import api, kc  # noqa: F401  (fixtures)

WALL_BELOW = [[[4.9, 0], [5.1, 0], [5.1, 1.5], [4.9, 1.5], [4.9, 0]]]
WALL_ABOVE = [[[4.9, 2.5], [5.1, 2.5], [5.1, 4], [4.9, 4], [4.9, 2.5]]]
WALL_DOOR = [[[4.9, 1.5], [5.1, 1.5], [5.1, 2.5], [4.9, 2.5], [4.9, 1.5]]]


def plan(door: bool = True) -> dict:
    """Two rooms (x 0..5 and 5..9, y 0..4), a wall between them with a door at y 1.5..2.5."""
    return {"bounds": [0, 0, 9, 4], "footprint": [[[[0, 0], [9, 0], [9, 4], [0, 4], [0, 0]]]],
            "walls": [WALL_BELOW, WALL_ABOVE] + ([] if door else [WALL_DOOR]), "partitions": [], "columns": [],
            "openings": []}


def test_way_through_the_door():
    w = routing.Walker(routing.build_grid(plan()))
    pts, length = w.path((2, 3.5), (7, 3.5))
    assert pts[0] == [2, 3.5] and pts[-1] == [7, 3.5]
    at_wall = [p for p in pts if 4.5 < p[0] < 5.5]
    assert at_wall and all(1.5 < p[1] < 2.5 for p in at_wall)              # through the opening
    assert length > 5.5
    assert w.path((2, 3.5), (2, 0.5))[1] == pytest.approx(3.0, abs=0.05)   # straight within a room
    assert routing.Walker(routing.build_grid(plan(door=False))).path((2, 3.5), (7, 3.5)) is None
    # furniture blocks the way: a cabinet in the doorway
    blocked = routing.build_grid(plan(), [planning.footprint((5.6, 2), 0, 1.0, 1.4)])
    assert routing.Walker(blocked).path((2, 3.5), (7, 3.5)) is None


def test_flow_checks():
    pts = lambda *p: [list(x) for x in p]  # noqa: E731
    r1 = {"id": "r1", "name": "Пациенты", "flow": "patients", "path": [{"floor": "c0", "pts": pts((0, 2), (9, 2))}]}
    r2 = {"id": "r2", "name": "Отходы", "flow": "dirty", "path": [{"floor": "c0", "pts": pts((4, 0), (4, 4))}]}
    r3 = {"id": "r3", "name": "Персонал", "flow": "staff", "path": [{"floor": "c0", "pts": pts((4, 0), (4, 4))}]}
    z = {"id": "z1", "name": "Стерилизация", "zone": "clean", "floor": "c0", "pts": pts((3, 1), (5, 1), (5, 3), (3, 3))}
    out = routing.check_flows([r1, r2, r3], [z])
    kinds = {(x["kind"], x["a"], x["b"]) for x in out}
    assert ("flows", "r1", "r2") in kinds and not any("r3" in (x["a"], x["b"]) and x["kind"] == "flows" for x in out)
    assert ("zone", "r2", "z1") in kinds and ("zone", "r1", "z1") not in kinds


def test_plan_route(world, api, monkeypatch):  # noqa: F811
    pid, room, editor = world["pid"], world["room"], world["editor"]
    monkeypatch.setattr(planning, "load_plan", lambda s, did, floor: plan())
    with db.session() as s:
        fid = s.execute(text("SELECT id FROM floors WHERE drawing_id = :d"), {"d": pid}).scalar()
        room2 = s.execute(text("INSERT INTO rooms (drawing_id, floor_id, idx, name, type, area, poly) VALUES "
                               "(:d, :f, 1, 'Процедурная', 'procedure', 16, :p) RETURNING id"),
                          {"d": pid, "f": fid, "p": json.dumps([[[5, 0], [9, 0], [9, 4], [5, 4], [5, 0]]])}).scalar()
    r, p = Tools("tok-viewer", pid), Tools("tok-editor", pid)
    res = r.call("plan_route", drawing=pid, stops=[{"room": room}, {"room": room2}], name="Приём → процедура")
    assert "problem" not in res and res["floors"] == ["c0"] and res["length"] > 3 and res["time"] > 0
    route = res["ops"][0]
    assert route["geom"] == "route" and route["props"]["stops"][1]["label"] == "Процедурная"
    assert route["props"]["path"][0]["pts"][0] == route["props"]["stops"][0]["at"]
    assert res["conflicts"] == []
    assert "error" in r.call("plan_route", drawing=pid, stops=[{"room": room}], name="x")
    assert "error" in r.call("plan_route", drawing=pid, stops=[{"room": room}, {"floor": "c9", "at": [1, 1]}])
    assert "error" in r.call("plan_route", drawing=pid, stops=[{"room": room}, {"room": room2}], flow="cats")

    # proposed and applied: the route stands with its way; a dirty one across it is a conflict
    prop = p.call("plan_route", drawing=pid, stops=[{"room": room}, {"room": room2}], name="Пациенты",
                  then="propose", summary="Маршрут пациентов")
    assert editor.post(f"/api/proposals/{prop['proposal']['id']}/apply").status_code == 200
    got = r.call("query_objects", drawing=pid, item=None)
    assert any(o["geom"] == "route" for o in got["objects"])
    dirty = r.call("plan_route", drawing=pid, stops=[{"floor": "c0", "at": [8, 3.5]}, {"floor": "c0", "at": [1, 3.5]}],
                   flow="dirty", name="Отходы")
    assert dirty["conflicts"] and dirty["conflicts"][0]["kind"] == "flows"
    prop = p.call("plan_route", drawing=pid, stops=[{"floor": "c0", "at": [8, 3.5]}, {"floor": "c0", "at": [1, 3.5]}],
                  flow="dirty", name="Отходы", then="propose", summary="Вынос отходов")
    assert editor.post(f"/api/proposals/{prop['proposal']['id']}/apply").status_code == 200
    ch = r.call("check_project", drawing=pid)
    assert ch["counts"]["flows"] == 1 and "пересекаются" in ch["flows"][0]["text"]

    # no way: the door walled up
    monkeypatch.setattr(planning, "load_plan", lambda s, did, floor: plan(door=False))
    assert "Нет прохода" in r.call("plan_route", drawing=pid, stops=[{"room": room}, {"room": room2}])["problem"]
