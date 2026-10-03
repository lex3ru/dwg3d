"""Placing and coverage for agents: geometry, and the MCP tools on a 5×4 m room."""
import math

from fastapi.testclient import TestClient
from shapely.geometry import Polygon

from dwg3d import planning
from test_agent_mcp import Agent, world  # noqa: F401  (fixture)
from test_auth import api, kc  # noqa: F401  (fixtures)

ROOM = Polygon([(0, 0), (5, 0), (5, 4), (0, 4)])


def test_geometry_follows_the_viewer():
    for nx, ny in ((0, 1), (1, 0), (0, -1), (-1, 0), (0.6, 0.8)):
        _, f = planning.axes(planning.facing(nx, ny))
        assert math.isclose(f[0], nx, abs_tol=1e-3) and math.isclose(f[1], ny, abs_tol=1e-3)
    assert math.isclose(planning.footprint((1, 1), 37, 2, 0.5).area, 1.0)
    z = planning.service_zone((0, 0), 0, 2, 0.5, 1.0)          # angle 0: front is -y
    assert z.bounds == (-1.0, -1.25, 1.0, -0.25)
    assert math.isclose(planning.sector((0, 0), 0, 90, 10).area, math.pi * 100 / 4, rel_tol=0.01)
    assert math.isclose(planning.sector((0, 0), 0, 360, 2).area, math.pi * 4, rel_tol=0.01)


def test_doors_from_the_plan():
    # a door 0.9 m wide in the left wall (x = 0, 0.2 thick), its leaf opening into the room
    plan = {"openings": [{"kind": "door", "center": [0, 2], "poly": [[[-0.1, 1.55], [-0.1, 2.45], [0.1, 2.45], [0.1, 1.55], [-0.1, 1.55]]],
                          "leaves": [[[0.1, 1.55], [1.0, 1.55]]]},
                         {"kind": "window", "center": [5, 2], "poly": [[[4.9, 1.5], [4.9, 2.5], [5.1, 2.5], [5.1, 1.5], [4.9, 1.5]]]}],
            "partitions": [[[[2.5, 3], [2.6, 3], [2.6, 4], [2.5, 4], [2.5, 3]]]], "columns": []}
    solids, doors = planning.obstacles_from_plan(plan)
    assert len(solids) == 1 and len(doors) == 2                # the way and the swing; not the window
    way = doors[0]
    assert way.contains(planning.Point(0.65, 2)) and not way.contains(planning.Point(0.75, 2))
    assert doors[1].contains(planning.Point(0.5, 1.8))
    # along the walls: nothing in front of the door, nothing on the partition
    fit = planning.Fitter(ROOM, solids + doors, 1.9, 0.65, 0.8, 0.2)
    for at, angle in planning._along_wall(fit, ROOM, 10):
        fp = planning.footprint(at, angle, 1.9, 0.65)
        assert all(fp.intersection(g).area < 1e-4 for g in solids + doors)


def test_along_wall_fits_the_room():
    fit = planning.Fitter(ROOM, [planning.footprint((2, 2), 0, 1.9, 0.65)], 1.9, 0.65, 0.8, 0.2)
    places = planning._along_wall(fit, ROOM, 10)
    assert places
    taken = planning.footprint((2, 2), 0, 1.9, 0.65)
    for at, angle in places:
        fp = planning.footprint(at, angle, 1.9, 0.65)
        assert ROOM.buffer(0.02).contains(fp) and fp.intersection(taken).area < 1e-4
        assert ROOM.buffer(0.02).contains(planning.service_zone(at, angle, 1.9, 0.65, 0.8))
        # back to the nearest wall: the front points into the room
        _, (fx, fy) = planning.axes(angle)
        assert ROOM.contains(planning.Point(at[0] + fx * 0.5, at[1] + fy * 0.5))
        assert min(at[0], at[1], 5 - at[0], 4 - at[1]) < 0.65 / 2 + 0.05
    fps = [planning.footprint(at, a, 1.9, 0.65) for at, a in places]
    assert all(a.intersection(b).area < 1e-4 for i, a in enumerate(fps) for b in fps[i + 1:])


def test_planning_tools(world, api):  # noqa: F811
    pid, room, editor = world["pid"], world["room"], world["editor"]
    ptok = editor.post(f"/api/projects/{pid}/agent-tokens", json={"name": "plan", "mode": "propose"}).json()["token"]
    with TestClient(api.app) as c:
        r, p, w = Agent(c, world["token"]), Agent(c, ptok), Agent(c, world["write"])
        # computing is reading: any token
        plan = r.call("place_in_room", drawing=pid, room=room, item="doc.couch", count=2)
        assert plan["floor"] == "c0" and plan["room"]["name"] == "Кабинет врача" and len(plan["places"]) == 2
        assert [o["op"] for o in plan["ops"]] == ["create", "create"] and plan["notes"] == []
        assert r.call("query_objects", drawing=pid)["total"] == 1                  # nothing changed
        many = r.call("place_in_room", drawing=pid, room=room, item="doc.couch", count=30)
        assert 0 < len(many["places"]) < 30 and "поместилось" in many["notes"][0]
        assert len(r.call("place_in_room", drawing=pid, room=room, item="rec.table", where="center")["places"]) == 1
        assert len(r.call("place_in_room", drawing=pid, room=room, item="rec.table", count=4, where="corners")["places"]) >= 2
        assert len(r.call("place_in_room", drawing=pid, room=room, item="rec.table", count=3, where="grid")["places"]) == 3
        assert "error" in r.call("place_in_room", drawing=pid, room=999999, item="doc.couch")
        assert "error" in r.call("place_in_room", drawing=pid, room=room, item="no.such")

        # then: propose (a propose token, with a summary) or apply (a write token)
        assert "error" in r.call("place_in_room", drawing=pid, room=room, item="doc.couch", then="propose", summary="x")
        assert "summary" in p.call("place_in_room", drawing=pid, room=room, item="doc.couch", then="propose")["error"]
        prop = p.call("place_in_room", drawing=pid, room=room, item="doc.couch", then="propose", summary="Кушетку к стене")
        assert prop["proposal"]["status"] == "open" and prop["proposal"]["counts"]["create"] == 1
        assert "error" in p.call("place_in_room", drawing=pid, room=room, item="doc.couch", then="apply")
        done = w.call("place_row", drawing=pid, floor="c0", item="sec.fisheye", start=[2.5, 2], end=[2.5, 2], then="apply")
        assert len(done["created"]) == 1 and r.call("query_objects", drawing=pid, item="sec.")["total"] == 1

        # a row: evenly, along the row; overlaps told
        row = r.call("place_row", drawing=pid, floor="c0", item="rec.table", start=[0.5, 0.5], end=[4.5, 0.5], count=5)
        assert [x["at"] for x in row["places"]] == [[0.5, 0.5], [1.5, 0.5], [2.5, 0.5], [3.5, 0.5], [4.5, 0.5]]
        assert {x["angle"] for x in row["places"]} == {0.0}
        assert len(r.call("place_row", drawing=pid, floor="c0", item="rec.table", start=[0, 3], end=[4, 3], step=2)["places"]) == 3
        over = r.call("place_row", drawing=pid, floor="c0", item="rec.table", start=[2, 2], end=[2, 2])
        assert "couch1" in over["notes"][0]
        assert "error" in r.call("place_row", drawing=pid, floor="c0", item="rec.table", start=[0, 0], end=[1, 0])

        # coverage: a fisheye in the middle sees the whole room, faces only near it
        cov = r.call("camera_coverage", drawing=pid, floor="c0")
        assert cov["cameras"] == 1
        rc = cov["rooms"][0]
        assert rc["seen"] > 99 and 0 < rc["identify"] < 100 and rc["unseen"] == []
        cams = r.call("query_objects", drawing=pid, item="sec.")["objects"][0]["layer"]      # the CCTV layer, made for it
        assert cams != world["layer"]
        assert r.call("camera_coverage", drawing=pid, floor="c0", layer=cams)["cameras"] == 1
        assert r.call("camera_coverage", drawing=pid, floor="c0", layer=world["layer"])["cameras"] == 0
        assert "error" in r.call("camera_coverage", drawing=pid, floor="c0", room=999999)
