import json

import pytest
import trimesh

from app.dwg.config import load_config
from app.dwg.extract import read_drawing
from app.dwg.floors import parse_floor_name, parse_mark
from app.dwg.pipeline import run

from .make_sample import make


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    return make(tmp_path_factory.mktemp("dxf") / "sample.dxf")


@pytest.fixture(scope="module")
def built(sample, tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    return run(sample, out, debug_png=False), out


def test_units_guessed_as_cm(sample):
    d = read_drawing(sample, load_config())
    assert (d.units, d.units_source) == ("cm", "heuristic")


def test_floors_detected_named_and_stacked(built):
    meta, _ = built
    fl = meta["floors"]
    assert [f["level"] for f in fl] == [1, 2]
    assert [f["name"] for f in fl] == ["План 1-го этажа", "План 2-го этажа"]
    assert fl[0]["elevation"] == pytest.approx(0.0)
    assert fl[1]["elevation"] == pytest.approx(3.3)
    assert fl[0]["height"] == pytest.approx(3.3)       # from the marks
    # floor 2 drawn 30 m right / 5 m up -> aligned back via the grid axes
    assert fl[1]["offset"] == pytest.approx([-30.0, -5.0], abs=0.01)
    assert "grid" in fl[1]["alignment"]


def test_walls_not_doubled_and_gaps_closed(built):
    meta, _ = built
    st = meta["floors"][0]["stats"]
    exterior = 12 * 8 - 11.4 * 7.4 + 12 * 0.1           # 11.64 m2 + insulation
    partition = 0.12 * (7.4 - 0.9)                       # 0.78 m2
    window_cut = 1.5 * 0.3
    assert st["wall_area_m2"] == pytest.approx(exterior + partition - window_cut, rel=0.03)
    assert st["partition_area_m2"] == 0                 # A-WALL is not a partition layer
    assert st["single_line_walls"] == 0                  # the 5 mm gap was snapped, not buffered


def test_openings_and_rooms(built):
    meta, _ = built
    st = meta["floors"][0]["stats"]
    assert st["openings"].get("window") == 1
    assert st["openings"].get("door") == 1
    rooms = meta["floors"][0]["rooms"]
    assert len(rooms) == 2
    assert sorted(r["area"] for r in rooms) == pytest.approx([(5 - 0.3) * 7.4, (11.7 - 5.12) * 7.4], rel=0.01)
    assert any(r["name"] == "Кабинет" for r in rooms)


def test_glb_structure(built):
    meta, out = built
    scene = trimesh.load(out / "model.glb")
    names = set(scene.graph.nodes)
    for f in meta["floors"]:
        assert f["node"] in names
        assert f"{f['node']}_walls" in names
        assert f"{f['node']}_glass" in names
    assert "roof" in names
    lo, hi = scene.bounds
    assert hi[1] == pytest.approx(3.3 * 2, abs=0.05)     # Y-up, top of roof
    assert json.loads((out / "metadata.json").read_text())["floors"]


def test_manual_floor_override(sample, tmp_path):
    cfg = {"floors": {"items": [{"candidate": "c1", "level": 5, "height": 4.0, "elevation": 20.0}]}}
    meta = run(sample, tmp_path, cfg, debug_png=False)
    f2 = meta["floors"][1]
    assert (f2["level"], f2["height"], f2["elevation"]) == (5, 4.0, 20.0)


@pytest.mark.parametrize("text,expected", [
    ("План 1-го этажа", (1, "floor")), ("План 12 этажа", (12, "floor")), ("ЭТАЖ 3", (3, "floor")),
    ("План подвала", (-1, "basement")), ("План кровли", (None, "roof")), ("Level 04", (4, "floor")),
    ("План технического этажа", (None, "tech")), ("Разрез 1-1", None),
])
def test_parse_floor_name(text, expected):
    assert parse_floor_name(text) == expected


def test_parse_mark():
    assert parse_mark("+4,150") == pytest.approx(4.15)
    assert parse_mark("-0.050") == pytest.approx(-0.05)
    assert parse_mark("±0,000") == 0.0
    assert parse_mark("4150") is None


def test_stairs_and_door_leaf(built):
    meta, out = built
    st = meta["floors"][0]["stats"]
    assert st["stairs"] == 1
    assert st["door_leaves"] == 1
    plan = json.loads((out / meta["floors"][0]["plan"]).read_text())
    door = next(o for o in plan["openings"] if o["kind"] == "door")
    (hx, hy), (tx, ty) = door["leaves"][0]
    assert (hx, hy) == pytest.approx((5.12, 3.0), abs=0.01)
    assert ((tx - hx) ** 2 + (ty - hy) ** 2) ** 0.5 == pytest.approx(0.9, abs=0.01)
    assert len(plan["stairs"]) == 1


def test_exports(built):
    meta, out = built
    assert meta["exports"] == {"glb": "model.glb", "obj": "model_obj.zip", "ifc": "model.ifc"}
    import ifcopenshell
    f = ifcopenshell.open(str(out / "model.ifc"))
    assert [s.Name for s in f.by_type("IfcBuildingStorey")][:2] == ["План 1-го этажа", "План 2-го этажа"]
    assert len(f.by_type("IfcWindow")) == 2 and len(f.by_type("IfcDoor")) == 2
    assert len(f.by_type("IfcSpace")) == 4 and len(f.by_type("IfcStair")) == 2
    # every door / window sits in an opening that voids its host wall
    voids, fills = f.by_type("IfcRelVoidsElement"), f.by_type("IfcRelFillsElement")
    assert len(f.by_type("IfcOpeningElement")) == len(voids) == len(fills) == 4
    assert all(v.RelatingBuildingElement.is_a("IfcWall") for v in voids)
    assert {x.RelatedBuildingElement.is_a() for x in fills} == {"IfcDoor", "IfcWindow"}
    assert not [w for w in f.by_type("IfcWall") if "Перемычк" in (w.Name or "")]
    import zipfile
    assert {"model.obj", "model.mtl"} <= set(zipfile.ZipFile(out / "model_obj.zip").namelist())


def test_manual_edits(sample, built, tmp_path):
    fid = built[0]["floors"][0]["id"]                     # floor 1
    edits = {fid: {
        "openings": [{"at": [8.0, 0.15], "kind": "vitrage"},        # window -> vitrage
                     {"at": [5.06, 3.45], "kind": "wall"}],         # fill the door
        "add_openings": [{"a": [2.0, 7.85], "b": [3.0, 7.85], "kind": "window"}],
        "add_walls": [{"a": [5.12, 5.0], "b": [11.7, 5.0], "thickness": 0.1}],
        "rooms": [{"at": [2.0, 5.0], "name": "Холл"}],
    }}
    meta = run(sample, tmp_path, {"edits": edits}, debug_png=False)
    f = meta["floors"][0]
    assert f["stats"]["openings"] == {"vitrage": 1, "window": 1}
    names = sorted(r["name"] for r in f["rooms"])
    assert "Холл" in names and len(f["rooms"]) == 3       # door filled + new wall: 3 spaces, hall named


def test_erase_wall_does_not_create_door(sample, built, tmp_path):
    fid = built[0]["floors"][0]["id"]
    # erase a 2 m piece of the north exterior wall: must become an open gap,
    # not an auto-detected "door" with a lintel
    edits = {fid: {"erase_walls": [{"a": [2.0, 7.85], "b": [4.0, 7.85], "width": 0.5}]}}
    meta = run(sample, tmp_path, {"edits": edits}, debug_png=False)
    st = meta["floors"][0]["stats"]
    assert st["openings"] == {"window": 1, "door": 1}
    assert st["wall_area_m2"] < built[0]["floors"][0]["stats"]["wall_area_m2"] - 0.5


def test_manual_opening_spans_wall_thickness(sample, built, tmp_path):
    fid = built[0]["floors"][0]["id"]
    # door drawn on the inner face of the 30 cm south wall, next to the corner
    # where the exterior wall meets the partition-free east wall
    edits = {fid: {"add_openings": [{"a": [10.0, 0.3], "b": [11.0, 0.3], "kind": "door"}],
                   "add_walls": [{"a": [5.12, 5.0], "b": [11.4, 5.0], "thickness": 0.1}]}}
    meta = run(sample, tmp_path, {"edits": edits}, debug_png=False)
    plan = json.loads((tmp_path / meta["floors"][0]["plan"]).read_text())
    door = next(o for o in plan["openings"] if o["source"] == "manual")
    ys = [p[1] for p in door["poly"][0]]
    assert min(ys) == pytest.approx(0.0, abs=0.02) and max(ys) == pytest.approx(0.3, abs=0.02)
    assert door["width"] == pytest.approx(1.0, abs=0.01)
    # the drawn wall stops 0.3 m short of the east wall: it is extended to meet
    # it and no automatic "door" appears at its ends
    assert meta["floors"][0]["stats"]["openings"] == {"window": 1, "door": 2}


def test_export_edited_dxf_roundtrip(sample, built, tmp_path):
    """Edits written into the DXF must reproduce the edited model on re-import."""
    from app.dwg.dxf_writer import export_edited_dxf

    fid = built[0]["floors"][0]["id"]
    edits = {fid: {
        # (an erased wall piece re-imports as a doorway: in a drawing a gap
        # with jambs is just that, so it is covered by a separate check)
        "add_walls": [{"a": [5.12, 5.0], "b": [11.7, 5.0], "thickness": 0.12}],
        "add_openings": [{"a": [0.3, 5.5], "b": [0.3, 6.7], "kind": "window"},
                         {"a": [8.5, 5.06], "b": [9.4, 5.06], "kind": "door"}],
        "openings": [{"at": [8.0, 0.15], "kind": "door"}],
        "rooms": [{"at": [2.0, 5.0], "name": "Холл"}],
    }}
    edits[fid]["add_openings"].append({"a": [11.7, 1.0], "b": [11.7, 2.5], "kind": "vitrage"})
    edited = run(sample, tmp_path / "a", {"edits": edits}, debug_png=False)
    out = tmp_path / "edited.dxf"
    stats = export_edited_dxf(sample, out, {"edits": edits})
    assert stats["floors"] == 1 and stats["trimmed"] > 0 and stats["doors"] == 2 and stats["windows"] == 2
    again = run(out, tmp_path / "b", debug_png=False)          # no edits this time
    f1 = next(f for f in edited["floors"] if f["id"] == fid)
    f2 = next(f for f in again["floors"] if f["level"] == f1["level"])
    assert f2["stats"]["openings"] == f1["stats"]["openings"]
    assert f2["stats"]["wall_area_m2"] == pytest.approx(f1["stats"]["wall_area_m2"], rel=0.05)
    assert f2["stats"]["rooms"] == f1["stats"]["rooms"]
    assert "Холл" in [r["name"] for r in f2["rooms"]]
    # the other floor is untouched
    other = [f for f in again["floors"] if f["level"] != f1["level"]][0]
    ref = [f for f in built[0]["floors"] if f["level"] == other["level"]][0]
    assert other["stats"]["openings"] == ref["stats"]["openings"]


def test_export_erase_trims_walls(sample, built, tmp_path):
    import ezdxf
    from app.dwg.dxf_writer import export_edited_dxf

    fid = built[0]["floors"][0]["id"]
    edits = {fid: {"erase_walls": [{"a": [2.0, 7.85], "b": [4.0, 7.85], "width": 0.5}]}}
    out = tmp_path / "erased.dxf"
    export_edited_dxf(sample, out, {"edits": edits})
    msp = ezdxf.readfile(out).modelspace()
    # no wall line of floor 1 passes through the erased area (cm units)
    for e in msp.query("LINE"):
        if e.dxf.layer in ("A-WALL", "Стены_правки"):
            (x0, y0), (x1, y1) = (e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)
            if min(y0, y1) > 760 and max(y0, y1) < 820:          # along the north wall
                assert max(x0, x1) <= 200.5 or min(x0, x1) >= 399.5
    jambs = [e for e in msp.query("LWPOLYLINE LINE") if e.dxf.layer == "Стены_правки"]
    assert len(jambs) == 2
