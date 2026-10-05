"""Functional layers: routes of people (stops on several floors, the computed
way as a cache) and zones; they follow their floors through rebuilds."""
import uuid

import pytest

from conftest import add_drawing
from dwg3d import db, store, viewdata
from dwg3d.models import Build, LayerObject


def _floor(fid, bbox, offset=(0.0, 0.0), elevation=0.0, name=None):
    return {"id": fid, "space": "Model", "owner": None, "bbox": list(bbox), "offset": list(offset),
            "elevation": elevation, "name": name or fid, "level": 1, "height": 3.0}


A, B = (0, 0, 30, 20), (100, 0, 130, 20)


def _drawing(floors) -> str:
    did = uuid.uuid4().hex[:12]
    with db.session() as s:
        add_drawing(s, did, current_build=1)
        s.add(Build(drawing_id=did, n=1, result={"floors": floors}, config={}, out_dir="out"))
        store.sync_floors(s, did, {"floors": floors})
    return did


def _apply(did, ops, **kw):
    with db.session() as s:
        return viewdata.apply(s, did, "object", ops, **kw)


def _layer(did, kind):
    from dwg3d import layers
    with db.session() as s:
        return layers.create(s, did, {"kind": kind}).id


ROUTE = {"flow": "patients", "name": "Приём терапевта",
         "stops": [{"floor": "c0", "at": [2, 2], "label": "Вход"}, {"floor": "c1", "at": [105, 5], "label": "Кабинет 12"}],
         "path": [{"floor": "c0", "pts": [[2, 2], [10, 2]]}, {"floor": "c1", "pts": [[110, 2], [105, 5]]}],
         "length": 21.5, "time": 45.0, "floors_changed": 1, "build": 1}


def test_route_objects(pg):
    did = _drawing([_floor("c0", A), _floor("c1", B, elevation=3.0)])
    routes = _layer(did, "routes")
    r = _apply(did, [{"op": "create", "id": "r1", "geom": "route", "layer": routes, "props": ROUTE}])["items"][0]
    assert r["geom"] == "route" and r["floor"] == "c0" and r["at"] == [2.0, 2.0] and "item" not in r
    assert [st["floor"] for st in r["props"]["stops"]] == ["c0", "c1"]
    assert [sg["floor"] for sg in r["props"]["path"]] == ["c0", "c1"] and r["props"]["length"] == 21.5
    with db.session() as s:                                # stored with floor row ids
        row = s.get(LayerObject, (did, "r1"))
        assert all(isinstance(st["floor"], int) for st in row.props["stops"])
    shapes_ = viewdata.view_data
    with db.session() as s:
        v = shapes_(s, did)
    assert [x["id"] for x in v["shapes"]] == ["r1"] and "furniture" not in v

    bad = [({**ROUTE, "flow": "nobody"}, "flow"), ({**ROUTE, "stops": ROUTE["stops"][:1]}, "stops"),
           ({**ROUTE, "stops": [{"floor": "c9", "at": [0, 0]}, ROUTE["stops"][1]]}, "c9")]
    for props, what in bad:
        with pytest.raises(viewdata.Invalid, match=what):
            _apply(did, [{"op": "create", "geom": "route", "layer": routes, "props": props}])
    # a route is not furniture, and furniture is not a route
    furn = _layer(did, "furniture")
    with pytest.raises(viewdata.Invalid, match="не принимает"):
        _apply(did, [{"op": "create", "geom": "route", "layer": furn, "props": ROUTE}])
    with pytest.raises(viewdata.Invalid, match="не принимает"):
        _apply(did, [{"op": "create", "floor": "c0", "item": "doc.couch", "at": [1, 1], "layer": routes}])
    # without a layer: the first routes layer
    r2 = _apply(did, [{"op": "create", "id": "r2", "geom": "route", "props": ROUTE}])["items"][0]
    assert r2["layer"] == routes
    # the way is recomputed by the viewer: an update replaces the cache
    upd = {**ROUTE, "path": None, "problem": "Нет прохода: двери закрыты"}
    r = _apply(did, [{"op": "update", "id": "r1", "version": r["version"], "props": upd}])["items"][0]
    assert "path" not in r["props"] and r["props"]["problem"].startswith("Нет прохода")


def test_zones(pg):
    did = _drawing([_floor("c0", A)])
    zones = _layer(did, "zones")
    z = _apply(did, [{"op": "create", "id": "z", "geom": "polygon", "layer": zones, "floor": "c0",
                      "points": [[0, 0], [5, 0], [5, 5], [0, 5]], "props": {"zone": "clean", "name": "Стерилизационная"}}])
    z = z["items"][0]
    assert z["points"][2] == [5.0, 5.0] and z["props"] == {"zone": "clean", "name": "Стерилизационная"}
    with pytest.raises(viewdata.Invalid, match="zone"):
        _apply(did, [{"op": "create", "geom": "polygon", "layer": zones, "floor": "c0",
                      "points": [[0, 0], [5, 0], [5, 5]], "props": {"zone": "hot"}}])
    with pytest.raises(viewdata.Invalid, match="точек"):
        _apply(did, [{"op": "create", "geom": "polygon", "layer": zones, "floor": "c0", "points": [[0, 0], [1, 1]]}])


def test_routes_and_zones_follow_their_floors(pg):
    did = _drawing([_floor("c0", A), _floor("c1", B, elevation=3.0)])
    routes, zones = _layer(did, "routes"), _layer(did, "zones")
    _apply(did, [{"op": "create", "id": "r", "geom": "route", "layer": routes, "props": ROUTE},
                 {"op": "create", "id": "z", "geom": "polygon", "layer": zones, "floor": "c1",
                  "points": [[100, 0], [104, 0], [104, 4]], "props": {"zone": "dirty"}}])
    # next build: the floors swap ids and the second sheet moves by (+2, +1)
    with db.session() as s:
        d = store.get_drawing(s, did, lock=True)
        old = store.current_build(s, d)
        new = {"floors": [_floor("c5", A), _floor("c0", B, offset=(2.0, 1.0), elevation=3.0)]}
        store.sync_floors(s, did, new, old.result)
        s.add(Build(drawing_id=did, n=2, result=new, config={}, out_dir="out"))
        s.flush()
        d.current_build = 2
    with db.session() as s:
        v = viewdata.view_data(s, did)
    r = next(x for x in v["shapes"] if x["id"] == "r")
    assert [st["floor"] for st in r["props"]["stops"]] == ["c5", "c0"]
    assert r["props"]["stops"][0]["at"] == [2, 2] and r["props"]["stops"][1]["at"] == [107.0, 6.0]
    assert r["props"]["path"][1]["pts"][0] == [112.0, 3.0] and r["floor"] == "c5"
    z = next(x for x in v["shapes"] if x["id"] == "z")
    assert z["floor"] == "c0" and z["points"][0] == [102.0, 1.0]
