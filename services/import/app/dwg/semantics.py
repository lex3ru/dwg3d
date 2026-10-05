"""Building semantics on top of the 2D plans: room types, label placement,
entrances and points of interest (stairs, lifts).

Room types are assigned by name patterns from `room_types` in the config
(first match wins, case-insensitive shell globs); an unnamed room that
covers a detected stair flight is a stair well. Everything here works in
plan coordinates; `to_gltf` converts to the viewer's Y-up frame.
"""
from __future__ import annotations

import fnmatch
import math

import numpy as np
from shapely.geometry import LineString, Point
from shapely.ops import polylabel

from .geometry import FloorPlan, _mp, _polys

FALLBACK_TYPE = "other"


def room_type_rules(cfg: dict) -> list[tuple[str, list[str]]]:
    return [(k, [p.casefold() for p in (v or {}).get("names") or []])
            for k, v in (cfg.get("room_types") or {}).items()]


def classify_name(name: str, rules) -> str | None:
    n = " ".join((name or "").split()).casefold()
    if not n:
        return None
    for t, pats in rules:
        if any(fnmatch.fnmatchcase(n, p) for p in pats):
            return t
    return None


def classify_room(room, plan: FloorPlan, rules) -> str:
    t = classify_name(room.name, rules)
    if t:
        return t
    # unnamed (or unknown) room that is mostly a stair flight -> stair well
    # (a hall with an open stair in it stays a hall)
    stair = sum(room.poly.intersection(st.poly).area for st in plan.stairs)
    if stair > 0 and (stair > 0.2 * room.poly.area or room.poly.area <= max(60.0, 5 * stair)):
        return "stair" if "stair" in dict(rules) else FALLBACK_TYPE
    return FALLBACK_TYPE


def legend(cfg: dict) -> list[dict]:
    out = []
    for k, v in (cfg.get("room_types") or {}).items():
        v = v or {}
        out.append({"type": k, "label": v.get("label", k), "color": v.get("color", "#e9e4da")})
    if not any(x["type"] == FALLBACK_TYPE for x in out):
        out.append({"type": FALLBACK_TYPE, "label": "Прочие", "color": "#ece6da"})
    return out


def _chord(poly, p, angle: float) -> float:
    """Length of the piece of the line through p (direction angle) inside poly that contains p."""
    u = np.array([math.cos(angle), math.sin(angle)])
    x0, y0, x1, y1 = poly.bounds
    big = math.hypot(x1 - x0, y1 - y0) + 1
    line = LineString([(p.x - u[0] * big, p.y - u[1] * big), (p.x + u[0] * big, p.y + u[1] * big)])
    inter = line.intersection(poly)
    segs = [g for g in getattr(inter, "geoms", [inter]) if g.length > 0]
    return min(segs, key=lambda g: g.distance(p)).length if segs else 0.0


def label_frame(poly) -> dict:
    """Where and how to lay a room name on the floor: the centre of the
    largest inscribed circle (so a ring-shaped hall does not get its label in
    a side passage), the text direction (plan angle, radians) along the
    longest chord through it, and the room size available for the text."""
    try:
        p = polylabel(poly, tolerance=0.05)
        if not poly.contains(p):
            raise ValueError
    except Exception:
        p = poly.representative_point()
    r = poly.boundary.distance(p)
    try:
        c = np.asarray(poly.minimum_rotated_rectangle.exterior.coords)[:4]
        e = c[1] - c[0] if np.hypot(*(c[1] - c[0])) >= np.hypot(*(c[2] - c[1])) else c[2] - c[1]
        long_angle = math.atan2(e[1], e[0])
    except Exception:
        long_angle = 0.0
    # keep text readable: never upside down
    if long_angle > math.pi / 2 + 1e-6:
        long_angle -= math.pi
    elif long_angle <= -math.pi / 2 + 1e-6:
        long_angle += math.pi
    cands = [(0.0, _chord(poly, p, 0.0)), (long_angle, _chord(poly, p, long_angle)),
             (math.pi / 2, _chord(poly, p, math.pi / 2))]
    horiz = cands[0][1]
    angle, width = max(cands, key=lambda a: a[1])
    if horiz >= 0.8 * width:                  # horizontal reads best when it fits nearly as well
        angle, width = 0.0, horiz
    return {"x": p.x, "y": p.y, "angle": round(angle, 4),
            "w": round(0.85 * width, 3), "d": round(0.8 * 2 * r, 3)}


def to_gltf(x, y, z, center):
    return [round(x - center[0], 3), round(z, 3), round(-(y - center[1]), 3)]


# ----------------------------------------------------------- entrances ---
def entrance_floor(floors):
    """The floor people enter the building on: elevation closest to 0 among
    storeys that are not basements (fallback: the lowest floor)."""
    above = [f for f in floors if f.kind not in ("basement", "roof")]
    pool = above or floors
    return min(pool, key=lambda f: (abs(f.elevation), f.elevation)) if pool else None


def _outward(center, direction, footprint, step=0.6):
    """Unit normal of an opening pointing out of the building (or None)."""
    c = np.asarray(center, float)
    n = np.array([-direction[1], direction[0]], float)
    out_a = not footprint.contains(Point(c + n * step))
    out_b = not footprint.contains(Point(c - n * step))
    if out_a == out_b:
        return None
    return n if out_a else -n


def find_entrances(floors, plans, cfg: dict, center) -> list[dict]:
    """Exterior doors of the entrance floor (or the manual list from
    `building.entrances`). The main one is marked `main`."""
    f = entrance_floor(floors)
    if f is None:
        return []
    plan = plans[floors.index(f)]
    fp = plan.footprint
    if fp.is_empty:
        return []
    boundary = _mp(_polys(fp)).boundary
    found = []
    manual = (cfg.get("building") or {}).get("entrances") or []
    if manual:
        for m in manual:
            at = np.asarray(m["at"], float)
            # direction of the nearest outline edge
            d = boundary.project(Point(at))
            p0, p1 = boundary.interpolate(max(d - 0.3, 0)), boundary.interpolate(d + 0.3)
            u = np.array([p1.x - p0.x, p1.y - p0.y])
            u = u / (np.hypot(*u) or 1)
            n = _outward(at, u, fp, 0.8)
            found.append({"center": at, "normal": n if n is not None else np.array([0.0, -1.0]),
                          "width": float(m.get("width", 1.2)), "name": str(m.get("name", "")),
                          "main": bool(m.get("main", False)), "score": 0.0})
    else:
        for o in plan.openings:
            if o.kind not in ("door", "passage", "vitrage"):
                continue
            if o.poly.distance(boundary) > 0.08:
                continue
            n = _outward(o.center, o.direction, fp, max(0.6, o.depth))
            if n is None:
                continue
            if o.kind == "vitrage" and not o.leaves:      # plain glazing, not a door
                continue
            inside = Point(np.asarray(o.center) - n * (o.depth / 2 + 0.7))
            room = next((r for r in plan.rooms if r.poly.contains(inside)), None)
            score = o.width + (0.01 * min(room.area, 300) if room else 0) + (0.5 if o.kind == "door" else 0)
            found.append({"center": np.asarray(o.center, float), "normal": n, "width": round(o.width, 2),
                          "name": "", "main": False, "score": score})
    if not found:
        return []
    if not any(e["main"] for e in found):
        max(found, key=lambda e: e["score"])["main"] = True
    found.sort(key=lambda e: (not e["main"], -e["score"]))
    out = []
    for i, e in enumerate(found):
        letter = chr(ord("A") + i) if i < 26 else str(i + 1)
        c, n = e["center"], e["normal"]
        out.append({
            "id": f"e{i}", "label": letter, "main": e["main"], "floor": f.id, "width": e["width"],
            "name": e["name"] or ("Главный вход" if e["main"] else f"Вход {letter}"),
            "pos": to_gltf(c[0], c[1], f.elevation, center),
            "dir": [round(float(n[0]), 4), round(float(-n[1]), 4)],       # outward, glTF X/Z
        })
    return out


def floor_pois(f, plan: FloorPlan, room_types: list[str], center) -> list[dict]:
    """Stairs and lifts of one floor as viewer points of interest."""
    pois = []
    for st in plan.stairs:
        c = st.poly.centroid
        pois.append({"kind": "stair", "floor": f.id, "pos": to_gltf(c.x, c.y, f.elevation, center)})
    for r, t in zip(plan.rooms, room_types):
        if t == "lift":
            c = r.poly.representative_point()
            pois.append({"kind": "lift", "floor": f.id, "pos": to_gltf(c.x, c.y, f.elevation, center)})
    return pois
