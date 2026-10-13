"""Plans drawn in the 2D editor: kept here, saved over the version one started from, built like drawings."""
from __future__ import annotations

import copy

import pytest

from app.dwg.config import load_config
from app.sketch import SketchError, SketchScene, plan_of, read_sketch

from .conftest import BUILDING, upload
from .test_drawings import events

API = "/api/import/v1"


def wall(a: str, b: str, t: float = 0.25, kind: str = "bearing") -> dict:
    return {"a": a, "b": b, "thickness": t, "height": None, "kind": kind}


def two_rooms(floor_id: str = "f1") -> dict:
    """4 × 3 m on the centre lines, 25 cm outer walls, a 10 cm partition at x = 2 with a door; a window."""
    return {"version": 1, "floors": [{
        "id": floor_id, "name": "Этаж 1", "level": 1, "elevation": 0, "height": 2.7,
        "nodes": {"a": [0, 0], "e": [2, 0], "b": [4, 0], "c": [4, 3], "f": [2, 3], "d": [0, 3]},
        "walls": {"w1": wall("a", "e"), "w2": wall("e", "b"), "w3": wall("b", "c"), "w4": wall("c", "f"),
                  "w5": wall("f", "d"), "w6": wall("d", "a"), "p": wall("e", "f", 0.1, "partition")},
        "openings": {
            "door": {"wall": "p", "kind": "door", "at": 1.5, "width": 0.9, "height": 2.1, "sill": 0, "hinge": "a",
                     "side": "left"},
            "win": {"wall": "w3", "kind": "window", "at": 1.5, "width": 1.2, "height": 1.5, "sill": 0.8, "hinge": "a",
                    "side": "left"}},
        "rooms": {"r1": {"at": [1, 1.5], "name": "Кухня", "number": "101", "type": None}},
    }]}


async def new_sketch(client, tokens, **body) -> dict:
    r = await client.post(f"{API}/sketches", json={"building_id": BUILDING, **body}, headers=tokens.admin())
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ the plan ---
def test_rooms_are_measured_inside_the_walls_as_in_the_editor():
    plan = plan_of(read_sketch(two_rooms())["floors"][0], load_config({}))
    rooms = sorted(plan.rooms, key=lambda r: r.name)
    assert [r.name for r in rooms] == ["", "Кухня"]
    # (2 − 0.125 − 0.05) × (3 − 0.25), the same as findRooms in frontend/src/plan
    assert all(abs(r.area - 1.825 * 2.75) < 0.01 for r in rooms)
    assert sorted(o.kind for o in plan.openings) == ["door", "window"]
    door = next(o for o in plan.openings if o.kind == "door")
    assert len(door.leaves) == 1 and abs(door.width - 0.9) < 1e-6
    # the openings are cut through the walls
    assert all(plan.walls.intersection(o.poly).area < 1e-4 for o in plan.openings)


def test_each_opening_stands_at_its_own_height_in_3d():
    s = two_rooms()
    ops = s["floors"][0]["openings"]
    ops["door"].update(height=2.0)                                   # a low door
    ops["win"].update(sill=0.6, height=1.8)                          # a tall window, low sill
    cfg = load_config({})
    plan = plan_of(read_sketch(s)["floors"][0], cfg)
    sb = SketchScene(cfg, (0.0, 0.0))
    sb.floor("f1", plan, 0.0, 2.7, {})
    z = {name: (round(float(m.vertices[:, 2].min()), 3), round(float(m.vertices[:, 2].max()), 3))
         for name, m in sb.meshes.items()}
    top = 2.7 - cfg["building"]["slab_thickness"]
    assert z["floor_f1_glass"] == (0.6, 2.4)
    assert z["floor_f1_doors"] == (0.01, 1.99)
    # the wall under the window's sill and over both openings, up to the ceiling
    assert z["floor_f1_more_walls"] == (0.0, round(top, 3))
    assert z["floor_f1_more_partitions"] == (2.0, round(top, 3))
    # the walls themselves are cut through: the openings are filled only where they are not
    assert len(plan.openings) == 2


def test_a_low_wall_stands_to_its_own_height_in_3d():
    s = two_rooms()
    f = s["floors"][0]
    f["walls"]["p"]["height"] = 1.2                                  # the partition is a half-wall
    del f["openings"]["win"]                                         # its door (2.1 m) is higher than it
    cfg = load_config({})
    plan = plan_of(read_sketch(s)["floors"][0], cfg)
    sb = SketchScene(cfg, (0.0, 0.0))
    sb.floor("f1", plan, 0.0, 2.7, {})
    z = {name: (round(float(m.vertices[:, 2].min()), 3), round(float(m.vertices[:, 2].max()), 3))
         for name, m in sb.meshes.items()}
    top = round(2.7 - cfg["building"]["slab_thickness"], 3)
    assert z["floor_f1_walls"] == (0.0, top)
    assert z["floor_f1_more_partitions"] == (0.0, 1.2)
    assert z["floor_f1_doors"] == (0.01, 1.19)                        # cut by the wall's top, nothing above it
    assert "floor_f1_partitions" not in z                            # no full-height partition left
    # where the half-wall meets the outer walls, the outer walls stand: nothing is built twice
    half = plan.low_parts[0][0]
    assert half.intersection(plan.full_parts["wall"]).area < 1e-6
    # in 2D it is a wall like any other: it still parts the rooms
    assert len(plan.rooms) == 2 and plan.wall_parts["partition"].area > 0.15  # 2.75 m × 10 cm less the door


def test_a_wall_standing_inside_a_room_is_taken_out_of_it():
    s = two_rooms()
    f = s["floors"][0]
    f["nodes"].update(x=[2.6, 1.5], y=[3.6, 1.5])
    f["walls"]["free"] = wall("x", "y", 0.1, "partition")
    plan = plan_of(read_sketch(s)["floors"][0], load_config({}))
    right = max(plan.rooms, key=lambda r: r.poly.centroid.x)
    assert abs(right.area - (1.825 * 2.75 - 1.0 * 0.1)) < 0.01


def test_broken_sketches_are_refused_with_the_place():
    s = two_rooms()
    with pytest.raises(SketchError, match="версия"):
        read_sketch({**s, "version": 2})
    bad = copy.deepcopy(s)
    bad["floors"][0]["walls"]["w1"]["b"] = "nowhere"
    with pytest.raises(SketchError, match=r"walls\.w1.*узел"):
        read_sketch(bad)
    bad = copy.deepcopy(s)
    bad["floors"][0]["openings"]["door"]["kind"] = "hatch"
    with pytest.raises(SketchError, match="kind"):
        read_sketch(bad)

    # a curved wall: its faces name the curve, the curve its ends
    curved = copy.deepcopy(s)
    curved["floors"][0]["curves"] = {"k": {"a": "a", "b": "e", "bulge": -0.5, "segments": 2}}
    curved["floors"][0]["walls"]["w1"]["curve"] = "k"
    f = read_sketch(curved)["floors"][0]
    assert f["curves"]["k"]["bulge"] == -0.5 and f["walls"]["w1"]["curve"] == "k" and "curve" not in f["walls"]["w2"]
    curved["floors"][0]["walls"]["w2"]["curve"] = "nope"
    with pytest.raises(SketchError, match=r"walls\.w2\.curve"):
        read_sketch(curved)


# --------------------------------------------------------------- requests ---
async def test_draw_save_build(client, app, worker, tokens):
    admin = tokens.admin()
    d = await new_sketch(client, tokens, name="Корпус Б")
    assert d["kind"] == "sketch" and d["name"] == "Корпус Б" and d["sketch_version"] == 1 and d["build"] is None
    got = (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=admin)).json()
    assert got["version"] == 1 and len(got["sketch"]["floors"]) == 1 and got["sketch"]["floors"][0]["walls"] == {}

    # an empty plan is not built
    assert (await client.post(f"{API}/drawings/{d['id']}/builds", json={}, headers=admin)).status_code == 422

    saved = await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": two_rooms(), "version": 1},
                             headers=admin)
    assert saved.status_code == 200 and saved.json() == {"version": 2}
    # saved over a version that is gone: refused, and told which is current
    stale = await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": two_rooms(), "version": 1},
                             headers=admin)
    assert stale.status_code == 409 and stale.json()["code"] == "conflict" and stale.json()["version"] == 2

    r = await client.post(f"{API}/drawings/{d['id']}/builds", json={}, headers=admin)
    assert r.status_code == 202 and r.json()["build"]["status"] == "queued"
    # what is saved after the build began does not change it
    later = two_rooms()
    later["floors"][0]["name"] = "Изменён позже"
    assert (await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": later, "version": 2},
                             headers=admin)).status_code == 200
    assert await worker.run_once() is True

    d = (await client.get(f"{API}/drawings/{d['id']}", headers=admin)).json()
    assert d["build"]["status"] == "done", d["build"]
    result = (await client.get(f"{API}/builds/{d['build']['id']}/result", headers=admin)).json()["result"]
    [floor] = result["floors"]
    assert floor["id"] == "f1" and floor["name"] == "Этаж 1" and floor["owner"] == "f1" and floor["bbox"]
    assert sorted(r["name"] for r in floor["rooms"]) == ["", "Кухня"]
    assert result["quality"]["status"] == "ok" and result["source"] == "sketch"
    plan = (await client.get(f"{API}/builds/{d['build']['id']}/files/{floor['plan']}", headers=admin)).json()
    assert len(plan["rooms"]) == 2 and sorted(o["kind"] for o in plan["openings"]) == ["door", "window"]
    # the number given in the editor goes with its room; a room without a label has none
    assert sorted((r["name"], r["number"]) for r in plan["rooms"]) == [("", ""), ("Кухня", "101")]
    model = await client.get(f"{API}/builds/{d['build']['id']}/files/model.glb", headers=admin)
    assert model.status_code == 200 and model.content[:4] == b"glTF"

    happened = [e["type"] for e in await events(app)]
    assert happened == ["import.drawing.drawn", "import.build.started", "import.build.finished"]


async def test_a_sketch_is_not_a_file(client, tokens, sample):
    admin = tokens.admin()
    d = await new_sketch(client, tokens)
    files = {"file": ("plan.dxf", sample, "application/octet-stream")}
    r = await client.post(f"{API}/drawings/{d['id']}/files", files=files, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "sketch"
    assert (await client.get(f"{API}/drawings/{d['id']}/export", headers=admin)).status_code == 409
    broken = two_rooms()
    broken["floors"][0]["walls"]["w1"]["thickness"] = 0
    r = await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": broken, "version": 1}, headers=admin)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "sketch"


async def test_who_may_draw(client, tokens, grants):
    d = await new_sketch(client, tokens)
    body = {"sketch": two_rooms(), "version": 1}
    stranger = tokens.bearer("user-1")
    assert (await client.post(f"{API}/sketches", json={"building_id": BUILDING}, headers=stranger)).status_code == 404
    assert (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=stranger)).status_code == 404

    grants["viewer"] = [{"role": "viewer", "scope": {"kind": "building", "id": BUILDING}, "building_id": BUILDING}]
    viewer = tokens.bearer("viewer")
    assert (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=viewer)).status_code == 200
    assert (await client.put(f"{API}/drawings/{d['id']}/sketch", json=body, headers=viewer)).status_code == 403
    assert (await client.post(f"{API}/sketches", json={"building_id": BUILDING}, headers=viewer)).status_code == 403

    grants["boss"] = [{"role": "admin", "scope": {"kind": "building", "id": BUILDING}, "building_id": BUILDING}]
    boss = tokens.bearer("boss")
    assert (await client.put(f"{API}/drawings/{d['id']}/sketch", json=body, headers=boss)).status_code == 200


# a 1 × 1 PNG
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


async def test_a_picture_to_draw_over(client, worker, tokens):
    admin = tokens.admin()
    d = await new_sketch(client, tokens)
    url = f"{API}/drawings/{d['id']}/underlays"
    r = await client.post(url, files={"file": ("plan.png", PNG, "image/png")}, headers=admin)
    assert r.status_code == 201, r.text
    name = r.json()["id"]
    assert name.endswith(".png")
    got = await client.get(f"{url}/{name}", headers=admin)
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    assert (await client.get(f"{url}/x.png", headers=admin)).status_code == 404
    assert (await client.get(f"{url}/{'0' * 32}.png", headers=admin)).status_code == 404

    # what is not a picture is refused, whatever its name says
    r = await client.post(url, files={"file": ("plan.png", b"%PDF-1.7 ...", "image/png")}, headers=admin)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "file"

    # the plan keeps it on its floor; the build does not mind it
    s = two_rooms()
    s["floors"][0]["underlay"] = {"image": name, "at": [-1, -1], "scale": 0.01, "rotation": 30, "width": 600,
                                  "height": 400, "opacity": 0.5, "hidden": False}
    assert (await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": s, "version": 1},
                             headers=admin)).status_code == 200
    back = (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=admin)).json()["sketch"]
    assert back["floors"][0]["underlay"]["image"] == name and back["floors"][0]["underlay"]["rotation"] == 30
    assert (await client.post(f"{API}/drawings/{d['id']}/builds", json={}, headers=admin)).status_code == 202
    await worker.run_once()
    assert (await client.get(f"{API}/drawings/{d['id']}", headers=admin)).json()["build"]["status"] == "done"


async def test_only_a_drawn_plan_has_pictures(client, tokens, sample):
    from .conftest import upload
    d = (await upload(client, tokens, sample)).json()
    r = await client.post(f"{API}/drawings/{d['id']}/underlays", files={"file": ("p.png", PNG, "image/png")},
                          headers=tokens.admin())
    assert r.status_code == 409 and r.json()["code"] == "not_sketch"


async def test_a_drawn_plan_as_a_dxf_drawing(client, tokens, tmp_path):
    from urllib.parse import quote

    import ezdxf

    admin = tokens.admin()
    d = await new_sketch(client, tokens, name="Дача")
    url = f"{API}/drawings/{d['id']}/export"
    r = await client.get(url, params={"format": "dxf"}, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "nothing_to_export"      # no walls yet

    s = two_rooms()
    upper = copy.deepcopy(s["floors"][0])
    upper.update(id="f2", name="Этаж 2", level=2, elevation=2.7, openings={}, rooms={})
    s["floors"].append(upper)
    assert (await client.put(f"{API}/drawings/{d['id']}/sketch", json={"sketch": s, "version": 1},
                             headers=admin)).status_code == 200
    r = await client.get(url, params={"format": "dxf"}, headers=admin)
    assert r.status_code == 200 and quote("Дача.dxf") in r.headers["content-disposition"]
    (tmp_path / "plan.dxf").write_bytes(r.content)
    doc = ezdxf.readfile(tmp_path / "plan.dxf")
    msp = doc.modelspace()
    assert {"Стены", "Перегородки", "Проёмы", "Помещения", "Подписи"} <= {layer.dxf.name for layer in doc.layers}
    labels = [m.text for m in msp.query("MTEXT")]
    assert sum("101 Кухня" in t for t in labels) == 1 and len(labels) == 4          # two rooms on each floor
    assert len(msp.query('ARC[layer=="Проёмы"]')) == 1                                # the door's swing
    assert sorted(t.dxf.text for t in msp.query("TEXT")) == ["Этаж 1", "Этаж 2"]
    # the floors lie side by side, the second right of the first
    xs = sorted({round(p.dxf.insert[0], 3) for p in msp.query("TEXT")})
    assert len(xs) == 2 and xs[1] - xs[0] >= 4.25 + 5 - 0.01

    # the objects drawn on their floors, where they stand on the plan
    body = {"format": "dxf", "types": {"chair": {"id": "chair", "w": 0.5, "d": 0.5}},
            "objects": [{"floor": "f2", "at": [1, 1], "angle": 0, "type": "chair", "name": "Стул"}]}
    r = await client.post(url, json=body, headers=admin)
    assert r.status_code == 200 and r.headers["x-objects-drawn"] == "1"
    (tmp_path / "objects.dxf").write_bytes(r.content)
    [chair] = ezdxf.readfile(tmp_path / "objects.dxf").modelspace().query("INSERT")
    second = [t for t in msp.query("TEXT") if t.dxf.text == "Этаж 2"][0].dxf.insert
    assert abs(chair.dxf.insert[0] - (second[0] + 0.125 + 1)) < 1e-6       # 1 m right of the floor's left wall face


def test_the_ifc_of_a_drawn_plan_has_its_own_heights(tmp_path):
    import ifcopenshell

    from app.sketch import run

    s = two_rooms()
    f = s["floors"][0]
    f["walls"]["p"]["height"] = 2.3                                  # the partition stops short of the ceiling
    f["openings"]["door"].update(height=2.0)
    f["openings"]["win"].update(sill=0.6, height=1.8)
    meta = run(s, tmp_path)
    assert meta["exports"].get("ifc") == "model.ifc", meta["warnings"]
    model = ifcopenshell.open(str(tmp_path / "model.ifc"))

    def z(el):
        solid = el.Representation.Representations[0].Items[0]
        return round(solid.Position.Location.Coordinates[2], 3), round(solid.Depth, 3)

    [window] = model.by_type("IfcWindow")
    [door] = model.by_type("IfcDoor")
    assert (round(window.OverallHeight, 3), z(window)) == (1.8, (0.6, 1.8))
    assert (round(door.OverallHeight, 3), z(door)) == (2.0, (0.0, 2.0))
    assert sorted(z(o) for o in model.by_type("IfcOpeningElement")) == [(0.0, 2.0), (0.6, 1.8)]
    walls = {w.PredefinedType: z(w) for w in model.by_type("IfcWall")}
    top = round(2.7 - load_config({})["building"]["slab_thickness"], 3)
    assert walls == {"SOLIDWALL": (0.0, top), "PARTITIONING": (0.0, 2.3)}
    spaces = sorted((sp.Name, sp.LongName) for sp in model.by_type("IfcSpace"))
    assert spaces[0] == ("101", "Кухня")


def test_columns_and_stairs(tmp_path):
    import ifcopenshell

    from app.sketch import run

    s = two_rooms()
    f = s["floors"][0]
    f["columns"] = {"c1": {"at": [1, 0.8], "shape": "rect", "width": 0.4, "depth": 0.4, "angle": 0}}
    f["stairs"] = {"s1": {"at": [3, 1.5], "width": 1.0, "length": 2.0, "angle": 90, "steps": 15}}
    upper = copy.deepcopy(f)
    upper.update(id="f2", name="Этаж 2", level=2, elevation=2.7, openings={}, rooms={}, columns={}, stairs={})
    s["floors"].append(upper)
    cfg = load_config({})

    plan = plan_of(read_sketch(s)["floors"][0], cfg)
    kitchen = next(r for r in plan.rooms if r.name == "Кухня")
    assert abs(kitchen.area - (1.825 * 2.75 - 0.16)) < 0.01                    # the column taken out
    assert len(plan.stairs) == 1 and len(plan.stairs[0].treads) == 15
    assert abs(plan.stairs[0].riser - 0.18) < 1e-9                              # 2.7 m in 15 steps

    meta = run(s, tmp_path)
    floors = {fl["id"]: fl for fl in meta["floors"]}
    assert floors["f1"]["stats"]["columns"] == 1 and floors["f1"]["stats"]["stairs"] == 1
    model = ifcopenshell.open(str(tmp_path / "model.ifc"))
    assert len(model.by_type("IfcColumn")) == 1 and len(model.by_type("IfcStair")) == 1
    # the upper floor's slab has the opening over the flight: 2 m × 1 m less than the floor below's
    slabs = sorted((sl for sl in model.by_type("IfcSlab") if sl.PredefinedType == "FLOOR"),
                   key=lambda sl: sl.ContainedInStructure[0].RelatingStructure.Elevation)
    voids = [sl.Representation.Representations[0].Items[0].SweptArea for sl in slabs]
    assert voids[0].is_a("IfcArbitraryClosedProfileDef") and voids[1].is_a("IfcArbitraryProfileDefWithVoids")

    import ezdxf

    from app.sketch_dxf import sketch_dxf
    sketch_dxf(s, tmp_path / "plan.dxf")
    msp = ezdxf.readfile(tmp_path / "plan.dxf").modelspace()
    assert len(msp.query('LWPOLYLINE[layer=="Колонны"]')) == 1
    # the flight: its outline, 14 lines between 15 treads, the arrow's line and its two barbs
    assert len(msp.query('LWPOLYLINE[layer=="Лестницы"]')) == 1 and len(msp.query('LINE[layer=="Лестницы"]')) == 14 + 3


def test_the_roof_leaves_a_terrace_in_low_walls_open():
    # a 4 × 3 room and, east of it, a 2 × 3 terrace in walls 1 m high
    s = two_rooms()
    f = s["floors"][0]
    f["nodes"].update(g=[6, 0], h=[6, 3])
    f["walls"].update(t1=wall("b", "g"), t2=wall("g", "h"), t3=wall("h", "c"))
    for k in ("t1", "t2", "t3"):
        f["walls"][k]["height"] = 1.0
    plan = plan_of(read_sketch(s)["floors"][0], load_config({}))
    assert len(plan.rooms) == 3                                      # the terrace is a room on the plan
    assert abs(plan.roof_footprint.area - 4.25 * 3.25) < 0.01        # the roof only over the walls up to the ceiling
    assert plan.footprint.area > plan.roof_footprint.area + 5


# ------------------------------------------------------- a drawing turned into a plan ---
def test_walls_of_a_built_plan_come_back_as_centre_lines(tmp_path):
    """The sample's two floors: the outline of 30 cm walls and a 12 cm partition with a door, a window; the plan
    drawn of it closes the same rooms, of the same areas."""
    import json

    from app.dwg.pipeline import run
    from app.to_sketch import sketch_of

    from .make_sample import make

    meta = run(make(tmp_path / "sample.dxf"), tmp_path / "build", {}, debug_png=False)
    plans = {f["id"]: json.loads((tmp_path / "build" / f["plan"]).read_text()) for f in meta["floors"]}
    cfg = load_config({})
    sketch, notes = sketch_of(meta, plans, cfg)
    sketch = read_sketch(sketch)
    assert notes == [] and [f["level"] for f in sketch["floors"]] == [1, 2]
    for f in sketch["floors"]:
        built = next(m for m in meta["floors"] if m["id"] == f["id"])
        assert f["source"] == {"space": built["space"], "owner": built["owner"], "bbox": built["bbox"],
                               "offset": built["offset"]}
        assert sorted((w["kind"], w["thickness"]) for w in f["walls"].values()).count(("partition", 0.12)) == 1
        assert {w["thickness"] for w in f["walls"].values() if w["kind"] == "bearing"} <= {0.3, 0.4}
        assert sorted((o["kind"], round(o["width"], 1)) for o in f["openings"].values()) == [("door", 0.9),
                                                                                             ("window", 1.5)]
        door = next(o for o in f["openings"].values() if o["kind"] == "door")
        assert (door["hinge"], door["side"]) == ("a", "right")       # hinged at the lower jamb, into the office
        assert [r["name"] for r in f["rooms"].values()] == ["Кабинет"]
        assert len(f["stairs"]) == 1
        drawn = sorted(round(r.area, 1) for r in plan_of(f, cfg).rooms)
        assert drawn == sorted(round(r["area"], 1) for r in plans[f["id"]]["rooms"])


async def test_a_drawing_turned_into_a_plan_goes_on_as_the_same_drawing(client, app, worker, tokens, grants, sample):
    admin = tokens.admin()
    d = (await upload(client, tokens, sample)).json()
    # not built yet: nothing to take
    r = await client.post(f"{API}/drawings/{d['id']}/to-sketch", headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "not_ready"
    assert await worker.run_once() is True
    first = (await client.get(f"{API}/drawings/{d['id']}", headers=admin)).json()["build"]
    before = (await client.get(f"{API}/builds/{first['id']}/result", headers=admin)).json()["result"]["floors"]
    assert first["of"] == "file"

    grants["viewer"] = [{"role": "viewer", "scope": {"kind": "building", "id": BUILDING}, "building_id": BUILDING}]
    viewer = tokens.bearer("viewer")
    assert (await client.post(f"{API}/drawings/{d['id']}/to-sketch", headers=viewer)).status_code == 403
    r = await client.post(f"{API}/drawings/{d['id']}/to-sketch", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "sketch" and r.json()["id"] == d["id"] and r.json()["notes"] == []
    # once it is a plan, it is not taken again
    assert (await client.post(f"{API}/drawings/{d['id']}/to-sketch", headers=admin)).json()["code"] == "sketch"
    got = (await client.get(f"{API}/drawings/{d['id']}/sketch", headers=admin)).json()
    assert [f["id"] for f in got["sketch"]["floors"]] == [f["id"] for f in sorted(before, key=lambda f: f["level"])]
    assert all(f["walls"] and f["openings"] for f in got["sketch"]["floors"])
    drawn = [e for e in await events(app) if e["type"] == "import.drawing.drawn"]
    assert drawn[-1]["data"] == {"drawing_id": d["id"], "name": r.json()["name"], "from_file": True}

    # its build is of the same sheets: the building takes its floors for the ones it has
    assert (await client.post(f"{API}/drawings/{d['id']}/builds", json={}, headers=admin)).status_code == 202
    assert await worker.run_once() is True
    b = (await client.get(f"{API}/drawings/{d['id']}", headers=admin)).json()["build"]
    assert b["status"] == "done" and b["of"] == "sketch", b
    after = (await client.get(f"{API}/builds/{b['id']}/result", headers=admin)).json()["result"]["floors"]
    key = lambda f: (f["id"], f["space"], f["owner"], [round(v, 3) for v in f["bbox"]], f["offset"])  # noqa: E731
    assert sorted(map(key, after)) == sorted(map(key, before))
    areas = lambda fs: sorted(round(r["area"], 1) for f in fs for r in f["rooms"])  # noqa: E731
    assert areas(after) == areas(before)
