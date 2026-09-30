"""Furniture and pins follow their floors across rebuilds."""
from dwg3d.edits import remap_view


def _floor(fid, bbox, offset=(0.0, 0.0), elevation=0.0, name=None):
    return {"id": fid, "space": "Model", "owner": None, "bbox": list(bbox), "offset": list(offset),
            "elevation": elevation, "name": name or fid}


A, B = (0, 0, 30, 20), (100, 0, 130, 20)


def test_ids_swapped_and_offset_changed():
    old = {"center": [10.0, 5.0], "floors": [_floor("c0", A, name="1 этаж"), _floor("c1", B, elevation=3.0, name="2 этаж")]}
    # the next build detects the sheets in the other order and re-aligns the second one
    new = {"center": [12.0, 5.0], "floors": [_floor("c0", B, offset=(0.5, -1.0), elevation=3.3), _floor("c1", A)]}
    view = {
        "furniture": [{"id": "f1", "floor": "c0", "item": "doc.couch", "at": [5.0, 5.0], "angle": 0},
                      {"id": "f2", "floor": "c1", "item": "diag.mri", "at": [8.0, 2.0], "angle": 90}],
        "markers": [{"id": "m1", "floor": "c1", "pos": [1.0, 3.1, -2.0], "text": ""}],
        "site": {"lat": 1},
    }
    out, warns = remap_view(view, old, new)
    f = {it["id"]: it for it in out["furniture"]}
    assert f["f1"]["floor"] == "c1" and f["f1"]["at"] == [5.0, 5.0]
    assert f["f2"]["floor"] == "c0" and f["f2"]["at"] == [8.5, 1.0]
    m = out["markers"][0]
    # plan (1 + 10, 2 + 5) shifted by (0.5, -1) -> (11.5, 6); new centre (12, 5)
    assert m["floor"] == "c0" and m["pos"] == [-0.5, 3.4, -1.0]
    assert out["site"] == {"lat": 1} and not warns


def test_lost_floor_is_kept_aside_and_restored_later():
    old = {"floors": [_floor("c0", A), _floor("c1", B, name="Подвал")]}
    only_a = {"floors": [_floor("c0", A)]}
    view = {"furniture": [{"id": "f1", "floor": "c1", "item": "st.cabinet", "at": [101.0, 1.0], "angle": 0}],
            "comments": [{"id": "k1", "floor": "c1", "pos": [0, 0, 0], "text": "x"}]}
    out, warns = remap_view(view, old, only_a)
    assert out["furniture"] == [] and out["furniture_unplaced"][0]["id"] == "f1"
    assert out["comments"][0]["floor"] == ""          # kept as a building-wide pin
    assert warns and "Подвал" in warns[0]
    # the sheet comes back (as c5, shifted): the item returns to it
    back = {"floors": [_floor("c0", A), _floor("c5", B, offset=(2.0, 0.0))]}
    out2, warns2 = remap_view(out, only_a, back)
    assert "furniture_unplaced" not in out2 and not warns2
    assert out2["furniture"][0]["floor"] == "c5" and out2["furniture"][0]["at"] == [103.0, 1.0]
    assert "_anchor" not in out2["furniture"][0]


def test_nothing_to_do():
    assert remap_view(None, None, {"floors": []}) == (None, [])
    view = {"name": "x"}
    assert remap_view(view, {"floors": []}, {"floors": []})[0] == {"name": "x"}
