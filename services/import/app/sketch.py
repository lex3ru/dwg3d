"""Plans drawn in the 2D editor: reading them, and building them like a drawing.

A sketch (frontend/src/plan/model.ts) is a graph of walls: nodes, walls as the
centre line between two nodes with a thickness, openings placed on a wall by
the distance of their centre from its node `a`, and room labels by a point.
A floor may have a picture under it to draw over (`underlay`); the build
ignores it. Its build gives what a DWG build gives (app/dwg/pipeline.py) — floors with
rooms, plans/floor_<id>.json, model.glb, IFC and OBJ — so the buildings
service takes it the same way. The 3D model, room types, entrances and the
exports are the pipeline's own; only the plan comes from the sketch instead of
the drawing's linework.

The wall outlines follow the editor's (frontend/src/plan/outline.ts): at each
node the walls meet in turn, a corner where the faces of neighbours cross;
a wall alone ends square, walls in line step, too sharp a corner is cut.
"""
from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid

from .dwg.config import load_config
from .dwg.exports import export_ifc, export_obj_zip
from .dwg.floors import FloorCandidate
from .dwg.geometry import EMPTY, FloorPlan, Opening, Room, plan_to_json
from .dwg.model3d import SceneBuilder, _pane, extrude
from .dwg.semantics import classify_room, find_entrances, floor_pois, legend, room_type_rules

VERSION = 1
WALL_KINDS = ("bearing", "partition")
OPENING_KINDS = ("door", "window", "vitrage", "passage")
MITER_LIMIT = 6
EPS = 1e-9
Progress = Callable[[str, float, str], None]


class SketchError(ValueError):
    """The sketch is not one: what and where."""


# ------------------------------------------------------------------ reading ---
def _fail(path: str, what: str):
    raise SketchError(f"{path}: {what}")


def _obj(v, path: str) -> dict:
    return v if isinstance(v, dict) else _fail(path, "ожидался объект")


def _num(v, path: str, low: float = -math.inf) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        _fail(path, "ожидалось число")
    if v < low:
        _fail(path, f"не меньше {low}")
    return float(v)


def _str(v, path: str, limit: int = 200) -> str:
    if not isinstance(v, str):
        _fail(path, "ожидалась строка")
    if len(v) > limit:
        _fail(path, f"не длиннее {limit} знаков")
    return v


def _one(v, path: str, values: tuple[str, ...]) -> str:
    return v if v in values else _fail(path, "одно из: " + ", ".join(values))


def _xy(v, path: str) -> tuple[float, float]:
    if not isinstance(v, list) or len(v) != 2:
        _fail(path, "ожидалась точка [x, y]")
    return _num(v[0], f"{path}[0]"), _num(v[1], f"{path}[1]")


def _map(v, path: str, item) -> dict:
    return {k: item(x, f"{path}.{k}") for k, x in _obj(v, path).items()}


def _floor(v, path: str) -> dict:
    o = _obj(v, path)
    f = {
        "id": _str(o.get("id"), f"{path}.id", 64), "name": _str(o.get("name"), f"{path}.name"),
        "level": int(_num(o.get("level"), f"{path}.level")), "elevation": _num(o.get("elevation"), f"{path}.elevation"),
        "height": _num(o.get("height"), f"{path}.height", 0.5),
        "nodes": _map(o.get("nodes"), f"{path}.nodes", _xy),
        "walls": _map(o.get("walls"), f"{path}.walls", lambda x, p: {
            "a": _str(_obj(x, p).get("a"), f"{p}.a", 64), "b": _str(x.get("b"), f"{p}.b", 64),
            "thickness": _num(x.get("thickness"), f"{p}.thickness", 0.01),
            "height": None if x.get("height") is None else _num(x.get("height"), f"{p}.height", 0.1),
            "kind": _one(x.get("kind"), f"{p}.kind", WALL_KINDS)}),
        "openings": _map(o.get("openings"), f"{path}.openings", lambda x, p: {
            "wall": _str(_obj(x, p).get("wall"), f"{p}.wall", 64),
            "kind": _one(x.get("kind"), f"{p}.kind", OPENING_KINDS),
            "at": _num(x.get("at"), f"{p}.at"), "width": _num(x.get("width"), f"{p}.width", 0.1),
            "height": _num(x.get("height"), f"{p}.height", 0.1), "sill": _num(x.get("sill"), f"{p}.sill", 0),
            "hinge": _one(x.get("hinge"), f"{p}.hinge", ("a", "b")),
            "side": _one(x.get("side"), f"{p}.side", ("left", "right"))}),
        "rooms": _map(o.get("rooms"), f"{path}.rooms", lambda x, p: {
            "at": _xy(_obj(x, p).get("at"), f"{p}.at"), "name": _str(x.get("name"), f"{p}.name"),
            "number": _str(x.get("number"), f"{p}.number", 40),
            "type": None if x.get("type") is None else _str(x.get("type"), f"{p}.type", 60)}),
    }
    if o.get("underlay") is not None:
        u, p = _obj(o["underlay"], f"{path}.underlay"), f"{path}.underlay"
        f["underlay"] = {
            "image": _str(u.get("image"), f"{p}.image", 64), "at": _xy(u.get("at"), f"{p}.at"),
            "scale": _num(u.get("scale"), f"{p}.scale", 1e-6), "width": _num(u.get("width"), f"{p}.width", 1),
            "rotation": 0.0 if u.get("rotation") is None else _num(u.get("rotation"), f"{p}.rotation"),
            "height": _num(u.get("height"), f"{p}.height", 1), "opacity": _num(u.get("opacity"), f"{p}.opacity", 0),
            "hidden": u.get("hidden") is True}
    else:
        f["underlay"] = None
    for wid, w in f["walls"].items():
        if w["a"] not in f["nodes"] or w["b"] not in f["nodes"]:
            _fail(f"{path}.walls.{wid}", "конец стены ссылается на несуществующий узел")
        if w["a"] == w["b"]:
            _fail(f"{path}.walls.{wid}", "стена начинается и кончается в одном узле")
    for oid, op in f["openings"].items():
        if op["wall"] not in f["walls"]:
            _fail(f"{path}.openings.{oid}", "проём ссылается на несуществующую стену")
    return f


def read_sketch(v: Any) -> dict:
    """A sketch from untrusted JSON, checked as the editor checks it (parseSketch in frontend/src/plan/model.ts)."""
    o = _obj(v, "sketch")
    if o.get("version") != VERSION:
        _fail("sketch.version", f"поддерживается версия {VERSION}")
    if not isinstance(o.get("floors"), list) or not o["floors"]:
        _fail("sketch.floors", "ожидался непустой список")
    floors = [_floor(f, f"sketch.floors[{i}]") for i, f in enumerate(o["floors"])]
    if len({f["id"] for f in floors}) != len(floors):
        _fail("sketch.floors", "идентификаторы этажей повторяются")
    return {"version": VERSION, "floors": floors}


def empty_sketch(floor_id: str) -> dict:
    return {"version": VERSION, "floors": [{"id": floor_id, "name": "Этаж 1", "level": 1, "elevation": 0.0,
                                            "height": 2.7, "nodes": {}, "walls": {}, "openings": {}, "rooms": {}}]}


# ----------------------------------------------------------------- geometry ---
def _sub(a, b):
    return a[0] - b[0], a[1] - b[1]


def _add(a, b):
    return a[0] + b[0], a[1] + b[1]


def _mul(a, k):
    return a[0] * k, a[1] * k


def _perp(a):
    return -a[1], a[0]


def _unit(a):
    n = math.hypot(*a)
    return (a[0] / n, a[1] / n) if n > EPS else (0.0, 0.0)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _angle(a):
    r = math.atan2(a[1], a[0])
    return r + 2 * math.pi if r < 0 else r


def outlines(f: dict) -> dict[str, dict]:
    """Each wall's corners: a_plus, a_minus, b_plus, b_minus ("plus" is the face left of a→b)."""
    ends: dict[str, list[dict]] = {}
    for wid, w in f["walls"].items():
        a, b = f["nodes"][w["a"]], f["nodes"][w["b"]]
        d = _unit(_sub(b, a))
        ends.setdefault(w["a"], []).append({"wall": wid, "at_a": True, "dir": d, "h": w["thickness"] / 2})
        ends.setdefault(w["b"], []).append({"wall": wid, "at_a": False, "dir": _mul(d, -1), "h": w["thickness"] / 2})
    out: dict[str, dict] = {wid: {} for wid in f["walls"]}
    for node, items in ends.items():
        p = f["nodes"][node]
        items.sort(key=lambda e: _angle(e["dir"]))
        for i, e in enumerate(items):
            g = items[(i + 1) % len(items)]
            e_left = _add(p, _mul(_perp(e["dir"]), e["h"]))
            g_right = _add(p, _mul(_perp(g["dir"]), -g["h"]))
            left, right = e_left, g_right
            if e is not g:
                den = _cross(e["dir"], g["dir"])
                if abs(den) > 1e-12:
                    qp = _sub(g_right, e_left)
                    s, u = _cross(qp, g["dir"]) / den, _cross(qp, e["dir"]) / den
                    limit = MITER_LIMIT * max(e["h"], g["h"])
                    if abs(s) <= limit and abs(u) <= limit:
                        left = right = _add(e_left, _mul(e["dir"], s))
            # e's left corner, g's right corner
            if e["at_a"]:
                out[e["wall"]]["a_plus"] = left
            else:
                out[e["wall"]]["b_minus"] = left
            if g["at_a"]:
                out[g["wall"]]["a_minus"] = right
            else:
                out[g["wall"]]["b_plus"] = right
    return out


def _poly(points) -> Polygon | MultiPolygon:
    p = Polygon(points)
    return p if p.is_valid else make_valid(p).buffer(0)


def _polys(g) -> list[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [q for x in getattr(g, "geoms", []) for q in _polys(x)]


def _mp(geoms) -> Polygon | MultiPolygon:
    ps = _polys(unary_union([g for g in geoms if g is not None and not g.is_empty])) if geoms else []
    return EMPTY if not ps else ps[0] if len(ps) == 1 else MultiPolygon(ps)


def _faces(f: dict, w: dict, o: dict) -> tuple[float, float]:
    """Where along the wall (distance from a) both its faces exist."""
    a, b = f["nodes"][w["a"]], f["nodes"][w["b"]]
    d = _unit(_sub(b, a))

    def at(p):
        return (p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]
    length = math.dist(a, b)
    return max(0.0, at(o["a_plus"]), at(o["a_minus"])), min(length, at(o["b_plus"]), at(o["b_minus"]))


def plan_of(f: dict, cfg: dict) -> FloorPlan:
    """The 2D plan of a drawn floor, as the pipeline's plans are."""
    lines = outlines(f)
    # a wall lower than the floor (a half-wall, a counter) stands to its own height in 3D; None — up to the ceiling
    low = {i: w["height"] for i, w in f["walls"].items() if w["height"] is not None and w["height"] < f["height"]}
    # bearing walls are joined among themselves only: one stays whole where a partition meets it, the partition
    # stops at its face (joined with everything, the bearing wall would have a notch the partition fills)
    bearing = {i: w for i, w in f["walls"].items() if w["kind"] == "bearing"}
    bearing_lines = outlines({**f, "walls": bearing})
    bodies: dict[str, Polygon] = {}
    for wid, w in f["walls"].items():
        o = bearing_lines[wid] if wid in bearing else lines[wid]
        a, b = f["nodes"][w["a"]], f["nodes"][w["b"]]
        bodies[wid] = _poly([a, o["a_minus"], o["b_minus"], b, o["b_plus"], o["a_plus"]])

    openings: list[Opening] = []
    for op in f["openings"].values():
        w = f["walls"][op["wall"]]
        a, b = f["nodes"][w["a"]], f["nodes"][w["b"]]
        lo, hi = _faces(f, w, lines[op["wall"]])
        x0, x1 = max(lo, op["at"] - op["width"] / 2), min(hi, op["at"] + op["width"] / 2)
        if x1 - x0 < 0.05:
            continue                                        # off its wall: the editor reports it, the build skips it
        d = _unit(_sub(b, a))
        n = _perp(d)
        h = w["thickness"] / 2 + 0.001
        c0, c1 = _add(a, _mul(d, x0)), _add(a, _mul(d, x1))
        rect = Polygon([_add(c0, _mul(n, -h)), _add(c1, _mul(n, -h)), _add(c1, _mul(n, h)), _add(c0, _mul(n, h))])
        leaves = []
        if op["kind"] == "door":
            s = 1 if op["side"] == "left" else -1
            hinge = c0 if op["hinge"] == "a" else c1
            hp = _add(hinge, _mul(n, s * w["thickness"] / 2))
            leaves = [(hp, _add(hp, _mul(n, s * (x1 - x0))))]
        mid = _mul(_add(c0, c1), 0.5)
        o = Opening(kind=op["kind"], poly=rect, width=round(x1 - x0, 3), center=mid, direction=d,
                    source="manual", depth=w["thickness"], leaves=leaves)
        # its own heights (SketchScene), and the wall it is in, exactly as thick, to fill below and above it
        o.sill, o.head, o.wall_kind = op["sill"], op["sill"] + op["height"], w["kind"]
        o.wall_top = low.get(op["wall"])
        t = w["thickness"] / 2
        o.body = Polygon([_add(c0, _mul(n, -t)), _add(c1, _mul(n, -t)), _add(c1, _mul(n, t)), _add(c0, _mul(n, t))])
        openings.append(o)

    whole = {k: _mp([bodies[i] for i, w in f["walls"].items() if w["kind"] == k]) for k in WALL_KINDS}
    cut = _mp([o.poly for o in openings])
    parts = {"wall": whole["bearing"], "partition": _mp(_polys(whole["partition"].difference(whole["bearing"])))}
    if not cut.is_empty:
        parts = {k: _mp(_polys(v.difference(cut))) for k, v in parts.items()}
    walls = _mp(list(parts.values()))
    solid = _mp(list(whole.values()))

    # 3D: the walls up to the ceiling, and the lower ones by height, the higher first, none where a higher one is
    full = {k: _mp([bodies[i] for i, w in f["walls"].items() if w["kind"] == k and i not in low]) for k in WALL_KINDS}
    full_parts = {"wall": full["bearing"], "partition": _mp(_polys(full["partition"].difference(full["bearing"])))}
    taken = _mp(list(full.values()))
    low_parts: list[tuple[Polygon | MultiPolygon, float, str]] = []
    for h in sorted(set(low.values()), reverse=True):
        for kind in WALL_KINDS:
            g = _mp([bodies[i] for i, w in f["walls"].items() if low.get(i) == h and w["kind"] == kind])
            g = _mp(_polys(g.difference(taken))) if not taken.is_empty else g
            if g.is_empty:
                continue
            taken = _mp([taken, g])
            low_parts.append((g, h, "walls" if kind == "bearing" else "partitions"))
    if not cut.is_empty:
        full_parts = {k: _mp(_polys(v.difference(cut))) for k, v in full_parts.items()}
        low_parts = [(_mp(_polys(g.difference(cut))), h, r) for g, h, r in low_parts]

    # rooms: the spaces the walls close; groups of walls standing inside a room are taken out of it
    filled = [Polygon(p.exterior) for p in _polys(solid)]
    labels = sorted(f["rooms"].items())
    rooms = []
    for body in _polys(solid):
        for ring in body.interiors:
            space = Polygon(ring)
            inner = [x for x in filled if x.area < space.area and space.contains(x.representative_point())]
            room = _mp(_polys(space.difference(_mp([solid, *inner]))))
            for part in _polys(room):
                if part.area < float(cfg["geometry"]["min_room_area"]):
                    continue
                label = next((lb for _, lb in labels if part.contains(Point(lb["at"]))), None)
                r = Room(part, (label["name"] if label else "")[:60], round(part.area, 2))
                r.label_type = label["type"] if label else None
                r.number = label["number"].strip()[:40] if label else ""
                rooms.append(r)

    footprint = _mp(filled)
    plan = FloorPlan()
    plan.walls, plan.wall_parts, plan.columns = walls, parts, EMPTY
    plan.full_parts, plan.low_parts = full_parts, low_parts           # 3D only (SketchScene)
    plan.openings, plan.rooms, plan.footprint, plan.stairs = openings, rooms, footprint, []
    kinds: dict[str, int] = {}
    for o in openings:
        kinds[o.kind] = kinds.get(o.kind, 0) + 1
    plan.stats = {"walls": len(f["walls"]), "wall_area_m2": round(walls.area, 2),
                  "partition_area_m2": round(parts["partition"].area, 2), "columns": 0, "openings": kinds,
                  "door_leaves": sum(len(o.leaves) for o in openings), "stairs": 0, "rooms": len(rooms),
                  "footprint_m2": round(footprint.area, 2), "edits": 0}
    plan.debug = {"segments": [LineString([f["nodes"][w["a"]], f["nodes"][w["b"]]]) for w in f["walls"].values()]}
    return plan


# -------------------------------------------------------------------- 3D ---
class SketchScene(SceneBuilder):
    """The pipeline's scene, each opening at its own sill and height, each wall at its own height.

    The pipeline gives all doors one height and all windows one sill and head
    (building.door_height, window_sill, window_head). A drawn opening has its
    own: the walls are built with every opening cut through to the top, then
    each one gets the wall below its sill and above its head, its glass or its
    door leaf between. A wall lower than the floor stands to its own height,
    and so does what fills its openings."""

    def floor(self, fid: str, plan: FloorPlan, elevation: float, height: float, extras: dict,
              room_types: list[str] | None = None) -> tuple[int, list]:
        openings, plan.openings = plan.openings, []
        parts, plan.wall_parts = plan.wall_parts, getattr(plan, "full_parts", plan.wall_parts)
        try:
            node, rooms = super().floor(fid, plan, elevation, height, extras, room_types)
        finally:
            plan.openings, plan.wall_parts = openings, parts
        e = elevation
        top = e + height - float(self.cfg["building"]["slab_thickness"])
        if top - e < 1.0:                                       # as the pipeline does with pathological heights
            top = e + max(height, 2.0)
        fills: dict[str, list] = {"walls": [], "partitions": []}
        for g, h, role in getattr(plan, "low_parts", []):
            fills[role] += extrude(g, e, e + min(h, top - e))
        glass, doors = [], []
        for o in openings:
            role = "partitions" if o.wall_kind == "partition" else "walls"
            wall_top = min(o.wall_top, top - e) if o.wall_top is not None else top - e
            sill = min(max(o.sill, 0.0), wall_top)
            head = min(max(o.head, sill), wall_top)
            if sill > 0.001:
                fills[role] += extrude(o.body, e, e + sill)
            if head < wall_top - 0.001:
                fills[role] += extrude(o.body, e + head, e + wall_top)
            if head - sill < 0.01:
                continue
            if o.kind in ("window", "vitrage"):
                glass += extrude(_pane(o), e + sill, e + head)
            elif o.kind == "door":
                for hinge, tip in o.leaves:
                    leaf = LineString([hinge, tip]).buffer(0.02, cap_style="flat")
                    doors += extrude(leaf, e + sill + 0.01, e + head - 0.01)
        prefix = f"floor_{fid}"
        for name, meshes, role in ((f"{prefix}_more_walls", fills["walls"], "walls"),
                                   (f"{prefix}_more_partitions", fills["partitions"], "partitions"),
                                   (f"{prefix}_glass", glass, "glass"), (f"{prefix}_doors", doors, "doors")):
            child = self._add(name, meshes, role)
            if child is not None:
                self.w.nodes[node].setdefault("children", []).append(child)
        return node, rooms


# -------------------------------------------------------------------- build ---
def _noop(stage: str, frac: float, msg: str = "") -> None:
    pass


def run(sketch: dict, out_dir: Path, progress: Progress = _noop) -> dict:
    """Build a sketch into out_dir: model.glb, plans/floor_<id>.json, model.ifc, model_obj.zip, metadata.json;
    returns the metadata, as pipeline.run does for a drawing."""
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config({})
    sketch = read_sketch(sketch)
    drawn = sorted((f for f in sketch["floors"] if f["walls"]), key=lambda f: (f["level"], f["elevation"]))
    if not drawn:
        raise RuntimeError("В плане нет ни одной стены: нарисуйте стены, прежде чем собирать здание")

    warnings, plans, floors = [], [], []
    for i, f in enumerate(drawn):
        progress("geometry", 0.1 + 0.6 * i / len(drawn), f"Геометрия: {f['name']}")
        plan = plan_of(f, cfg)
        if not plan.rooms:
            warnings.append(f"{f['name']}: стены не замыкают ни одного помещения")
        x0, y0, x1, y1 = plan.footprint.bounds if not plan.footprint.is_empty else plan.walls.bounds
        floors.append(FloorCandidate(
            id=f["id"], source="sketch", bbox=(x0, y0, x1, y1), space="Sketch", owner=f["id"], name=f["name"],
            title_source="sketch", level=f["level"], elevation=f["elevation"], height=f["height"],
            elevation_source="sketch", height_source="sketch", alignment="reference", n_shapes=len(f["walls"])))
        plans.append(plan)

    progress("mesh", 0.75, "Построение 3D")
    allfp = _mp([p.footprint for p in plans])
    bx0, by0, bx1, by1 = allfp.bounds
    center = ((bx0 + bx1) / 2, (by0 + by1) / 2)
    sb = SketchScene(cfg, center)
    roots, floors_meta, pois = [], [], []
    rules = room_type_rules(cfg)
    known_types = {t["type"] for t in legend(cfg)}
    for f, plan in zip(floors, plans, strict=True):
        extras = {"id": f.id, "name": f.name, "level": f.level, "elevation": f.elevation, "height": f.height}
        # a type given in the editor, else by the name as for drawings
        types = [r.label_type if r.label_type in known_types else classify_room(r, plan, rules) for r in plan.rooms]
        node, rooms = sb.floor(f.id, plan, f.elevation, f.height, extras, types)
        roots.append(node)
        floors_meta.append({**f.to_dict(), "node": f"floor_{f.id}", "rooms": rooms, "stats": plan.stats,
                            "plan": f"plans/floor_{f.id}.json"})
        pois += floor_pois(f, plan, types, center)
    entrances = find_entrances(floors, plans, cfg, center)
    roof_node = None
    if cfg["building"].get("roof", True):
        n = sb.roof(plans[-1].footprint, floors[-1].elevation + floors[-1].height)
        if n is not None:
            roof_node = "roof"
            roots.append(n)

    progress("export", 0.85, "Экспорт glTF")
    glb = out_dir / "model.glb"
    sb.save(glb, roots, {"generator": "dwg3d-sketch"})
    plans_dir = out_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    for p in plans_dir.glob("floor_*.json"):
        p.unlink()
    for f, plan in zip(floors, plans, strict=True):
        data = plan_to_json(plan)
        for entry, r in zip(data["rooms"], plan.rooms, strict=True):    # the number given in the editor goes too
            entry["number"] = r.number
        (plans_dir / f"floor_{f.id}.json").write_text(json.dumps(data), encoding="utf-8")
    exports = {"glb": glb.name}
    for name, make in (("model_obj.zip", lambda p: export_obj_zip(p, sb.meshes)),
                       ("model.ifc", lambda p: export_ifc(p, floors, plans, cfg, center, "plan"))):
        (out_dir / name).unlink(missing_ok=True)
        try:
            make(out_dir / name)
            exports["obj" if name.endswith(".zip") else "ifc"] = name
        except Exception as ex:                                     # an export is extra: the build stands without it
            warnings.append(f"{name} не выгружен: {ex}")

    top = floors[-1].elevation + floors[-1].height
    meta = {
        "source": "sketch", "units": "m", "units_source": "sketch", "converter": "sketch",
        "model": glb.name, "center": [round(c, 4) for c in center], "floors": floors_meta, "roof_node": roof_node,
        "entrances": entrances, "pois": pois, "room_types": legend(cfg),
        "height_range": [floors[0].elevation - cfg["building"]["slab_thickness"], top],
        "extent": {"x": [round(bx0 - center[0], 2), round(bx1 - center[0], 2)],
                   "z": [round(center[1] - by1, 2), round(center[1] - by0, 2)]},
        "candidates": [], "exports": exports, "layers": {}, "triangles": sb.tri_count, "warnings": warnings,
        "quality": {"status": "ok" if all(p.rooms for p in plans) else "suspect",
                    "issues": [w for w in warnings if "помещени" in w]},
        "edits_unmatched": 0, "elapsed_s": round(time.time() - t0, 2),
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    progress("done", 1.0, "Готово")
    return meta
