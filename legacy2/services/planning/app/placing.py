# ruff: noqa: E501
"""Placing by rules and checks of what stands where — the code that counts, so the copilot only explains.

Conventions of the viewer (frontend/src/scene …/geom.ts, as the old planning.py):
  u = (cos a, sin a) — the item's width axis; f = (sin a, −cos a) — its front; footprint w along u, d along f, centred at (x, y).
An item stands inside its room (the room's outline stands for the walls), clear of other items standing on the floor,
of partitions and columns, and of the doors (the way through an opening with DOOR_CLEAR in front on both sides, and the
swing of each leaf). Items mounted at 1 m or higher (cameras, detectors, lights) are "high": they neither block nor are
blocked by the furniture. Detectors protect about 0.7·π·r² of floor each; cameras see a sector cut by their own room.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon  # noqa: F401  (Point is used by rules.py too)
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.validation import make_valid

WHERE = ("along_wall", "center", "corners", "grid", "front_of", "at_wall", "at_point")
ALONG = ("start", "middle", "end")
SEARCH_RADIUS = 2.0            # how far from the asked spot a place is looked for when the spot is taken
WALL_GAP = 0.01
DOOR_CLEAR = 0.6
MAX_ITEMS = 200
MAX_ROOMS = 100
NOT_FURNISHED = {"stair", "lift", "corridor", "wc", "technical"}
NO_CAMERAS_NEEDED = {"stair", "lift", "wc"}
NARROW_DOOR = 0.8

XY = tuple[float, float]


class PlanError(ValueError):
    """Cannot plan this (bad room, item…); the message is for the user."""


# -------------------------------------------------------------- geometry ---
def polygon(rings) -> Polygon | None:
    try:
        p = Polygon(rings[0], rings[1:])
        p = p if p.is_valid else make_valid(p)
        if p.geom_type == "MultiPolygon":
            p = max(p.geoms, key=lambda g: g.area)
        return p if p.geom_type == "Polygon" else None
    except Exception:
        return None


def axes(angle: float) -> tuple[XY, XY]:
    a = math.radians(angle)
    return (math.cos(a), math.sin(a)), (math.sin(a), -math.cos(a))


def facing(nx: float, ny: float) -> float:
    return round(math.degrees(math.atan2(nx, -ny)) % 360, 2)


def _rect(cx: float, cy: float, angle: float, hu: float, hf: float) -> Polygon:
    (ux, uy), (fx, fy) = axes(angle)
    return Polygon([(cx + ux * hu * su + fx * hf * sf, cy + uy * hu * su + fy * hf * sf)
                    for su, sf in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def footprint(at, angle: float, w: float, d: float) -> Polygon:
    return _rect(at[0], at[1], angle, w / 2, d / 2)


def _swing(hinge, tip, center) -> Polygon:
    r = math.dist(hinge, tip)
    a0 = math.atan2(tip[1] - hinge[1], tip[0] - hinge[0])
    da = math.atan2(center[1] - hinge[1], center[0] - hinge[0]) - a0
    da = (da + math.pi) % (2 * math.pi) - math.pi
    return Polygon([tuple(hinge)] + [(hinge[0] + r * math.cos(a0 + da * i / 6), hinge[1] + r * math.sin(a0 + da * i / 6)) for i in range(7)])


def openings(plan: dict) -> list[Polygon]:
    """The openings themselves — doors and windows — as the wall-mounted things may not hang over them."""
    out = []
    for o in plan.get("openings") or []:
        ring = o.get("poly") or []
        if len(ring) >= 3:
            g = Polygon(ring)
            if g.is_valid and g.area > 1e-4:
                out.append(g.buffer(0.15))
    return out


def obstacles(plan: dict) -> tuple[list[Polygon], list[Polygon]]:
    """(partitions and columns, door ways and swings) of a floor's plan (import's plans/floor_<id>.json)."""
    solids = [g for rings in (plan.get("partitions") or []) + (plan.get("columns") or [])
              if (g := polygon(rings)) is not None and not g.is_empty]
    doors = []
    for o in plan.get("openings") or []:
        if o.get("kind") == "window":
            continue
        ring = o.get("poly") or []
        if len(ring) >= 4:
            a, b2, c = ring[0], ring[1], ring[2]
            e1, e2 = math.dist(a, b2), math.dist(b2, c)
            along, across = ((b2[0] - a[0], b2[1] - a[1]), (c[0] - b2[0], c[1] - b2[1])) if e1 >= e2 else \
                ((c[0] - b2[0], c[1] - b2[1]), (b2[0] - a[0], b2[1] - a[1]))
            la, lc = math.hypot(*along) or 1, math.hypot(*across) or 1
            ang = math.degrees(math.atan2(along[1], along[0]))
            doors.append(_rect(o["center"][0], o["center"][1], ang, max(0.05, la / 2 - 0.02), lc / 2 + DOOR_CLEAR))
        for hinge, tip in o.get("leaves") or []:
            doors.append(_swing(hinge, tip, o["center"]))
    return solids, [g for g in doors if g.is_valid and g.area > 1e-4]


# -------------------------------------------------------------- the data ---
def size_of(t: dict | None) -> tuple[float, float, float]:
    s = (t or {}).get("size") or [0.5, 0.5, 0.5]
    return float(s[0] or 0.5), float(s[1] or 0.5), float(s[2] or 0.5)


def is_high(t: dict | None, elevation: float | None = None) -> bool:
    e = elevation if elevation is not None else (t or {}).get("elevation")
    return bool((t or {}).get("ceiling_mounted")) or (e or 0) >= 1


def is_wall_mounted(t: dict | None) -> bool:
    return bool((t or {}).get("wall_mounted"))


def value(t: dict | None, key: str) -> float | None:
    v = ((t or {}).get("values") or {}).get(key)
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def rooms_of(plan: dict) -> list[dict]:
    """The rooms of a floor plan with outlines: [{id, name, poly}] — without an id (retired, not matched) left out."""
    out = []
    for r in plan.get("rooms") or []:
        p = polygon(r.get("poly") or [])
        if r.get("id") and p is not None and not p.is_empty and p.area >= 0.5:
            out.append({"id": r["id"], "name": r.get("name") or "", "poly": p})
    return out


def standing(assets: list[dict], types: dict[str, dict]) -> list[tuple[dict, Polygon, bool]]:
    """(asset, footprint, high) of the objects on a floor."""
    out = []
    for a in assets:
        if a.get("x") is None or a.get("y") is None:
            continue
        t = types.get(a.get("type_id"))
        w, d, _ = size_of(t)
        out.append((a, footprint((a["x"], a["y"]), float(a.get("angle") or 0), w, d), is_high(t, a.get("elevation"))))
    return out


# -------------------------------------------------------------- placing ---
class Fitter:
    """Free places in a room: inside the outline, clear of the items standing there (with the gap between items) and
    of the hard things — partitions, columns, door ways — which the item may touch but not cross (no gap: a cabinet
    stands against a partition as it stands against a bearing wall). Items and hard things carry a label, so a
    refusal can say what is in the way."""

    def __init__(self, room: Polygon, items: list, hard: list, w: float, d: float, gap: float):
        self.room = room.buffer(0.02)
        self.items = [(t, label) for t, label in (self._labelled(x, "предмет") for x in items) if t.intersects(self.room)]
        self.hard = [(t, label) for t, label in (self._labelled(x, "перегородка или проём") for x in hard) if t.intersects(self.room)]
        self.w, self.d, self.gap = w, d, gap

    @staticmethod
    def _labelled(x, default: str) -> tuple[Polygon, str]:
        return x if isinstance(x, tuple) else (x, default)

    def blocker(self, at, angle: float) -> str | None:
        """Why the item cannot stand at `at`: None when it can."""
        fp = footprint(at, angle, self.w, self.d)
        if not self.room.contains(fp):
            return "выходит за контур помещения"
        for t, label in self.hard:
            if fp.intersection(t).area > 1e-4:
                return label
        grown = fp.buffer(self.gap / 2) if self.gap else fp
        for t, label in self.items:
            if grown.intersection(t).area > 1e-4:
                return f"налезает на {label}"
        return None

    def fits(self, at, angle: float) -> bool:
        return self.blocker(at, angle) is None

    def take(self, at, angle: float, label: str = "предмет") -> None:
        fp = footprint(at, angle, self.w, self.d)
        self.items.append((fp.buffer(self.gap / 2) if self.gap else fp, label))

    def nearest(self, at, angle: float, radius: float = SEARCH_RADIUS, step: float = 0.1) -> XY | None:
        """The free place closest to `at` with the same angle, within `radius`; None when there is none."""
        if self.fits(at, angle):
            return (round(at[0], 3), round(at[1], 3))
        (ux, uy), (fx, fy) = axes(angle)
        n = int(radius / step)
        cands = sorted(((math.hypot(i, j), (at[0] + ux * i * step + fx * j * step, at[1] + uy * i * step + fy * j * step))
                        for i in range(-n, n + 1) for j in range(-n, n + 1) if 0 < math.hypot(i, j) <= n), key=lambda c: c[0])
        for _, p in cands:
            if self.fits(p, angle):
                return (round(p[0], 3), round(p[1], 3))
        return None


def _frame(poly: Polygon) -> tuple[float, XY]:
    rect = poly.minimum_rotated_rectangle
    pts = list(rect.exterior.coords)[:4]
    sides = [(pts[i], pts[(i + 1) % 4]) for i in range(4)]
    (ax, ay), (bx, by) = max(sides, key=lambda e: math.dist(*e))
    c = poly.representative_point()
    return math.degrees(math.atan2(by - ay, bx - ax)), (c.x, c.y)


SIDES = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}


def side_of(dx: float, dy: float) -> str:
    """The side of the room a counter-clockwise edge lies on: its outward normal is to the right of the walk."""
    nx, ny = dy, -dx
    if abs(nx) >= abs(ny):
        return "east" if nx > 0 else "west"
    return "north" if ny > 0 else "south"


def walls_of(room: Polygon, min_length: float = 0.3) -> list[dict]:
    """The walls of the room in counter-clockwise order: {from, to, length, side, angle} — angle is the facing of an
    item standing with its back to that wall."""
    ring = orient(room, 1.0)
    pts = list(ring.exterior.coords)[:-1]
    out = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        length = math.dist(a, b)
        if length < min_length:
            continue
        tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        out.append({"from": a, "to": b, "length": length, "side": side_of(tx, ty), "angle": facing(-ty, tx), "t": (tx, ty)})
    return out


def _at_wall(fit: Fitter, room: Polygon, count: int, side: str, along, notes: list[str], from_end: bool = False) -> list[tuple[XY, float]]:
    """`count` items in a row with their backs to the wall on `side`, the row's near edge at `along` metres from the
    wall's start (walking counter-clockwise, as room_geometry lists the walls) — or from its end, with `from_end` —
    or at its start / middle / end; a taken spot is slid along the wall to the nearest free one and the shift is said."""
    walls = [w for w in walls_of(room) if w["side"] == side]
    if not walls:
        raise PlanError(f"у помещения нет стены со стороны {side}")
    wall = max(walls, key=lambda w: w["length"])
    (tx, ty), length = wall["t"], wall["length"]
    nx, ny = -ty, tx                                           # into the room
    off = fit.d / 2 + WALL_GAP
    row = count * fit.w + (count - 1) * fit.gap
    if isinstance(along, str):
        s0 = {"start": fit.w / 2, "middle": length / 2 - row / 2 + fit.w / 2, "end": length - row + fit.w / 2}.get(along)
        if s0 is None:
            raise PlanError(f"along: метры от начала стены или {', '.join(ALONG)}")
    else:
        s0 = (length - float(along) - row + fit.w / 2) if from_end else float(along) + fit.w / 2
    wanted = s0
    s0 = min(max(s0, fit.w / 2), max(length - row + fit.w / 2, fit.w / 2))
    if abs(s0 - wanted) > 0.01:
        notes.append(f"стена {side} длиной {round(length, 2)} м: ряд из {count} ({round(row, 2)} м) сдвинут на {round(abs(s0 - wanted), 2)} м, чтобы поместиться")
    out: list[tuple[XY, float]] = []
    shift = None
    for k in range(count):
        s = s0 + k * (fit.w + fit.gap)
        want = (wall["from"][0] + tx * s + nx * off, wall["from"][1] + ty * s + ny * off)
        at = (round(want[0], 3), round(want[1], 3))
        if not fit.fits(at, wall["angle"]):
            why = fit.blocker(at, wall["angle"])
            # slide along the wall both ways
            found = None
            for ds in sorted({i * 0.1 for i in range(1, int(length / 0.1) + 1)}):
                for sign in (1, -1):
                    s2 = s + sign * ds
                    if not fit.w / 2 - 1e-6 <= s2 <= length - fit.w / 2 + 1e-6:
                        continue
                    p = (round(wall["from"][0] + tx * s2 + nx * off, 3), round(wall["from"][1] + ty * s2 + ny * off, 3))
                    if fit.fits(p, wall["angle"]):
                        found = (p, sign * ds)
                        break
                if found:
                    break
            if not found:
                notes.append(f"на стене {side} в {round(s - fit.w / 2, 2)} м нет места: {why}; свободного места на этой стене тоже нет")
                break
            at, moved = found
            shift = (shift or 0) + abs(moved)
            notes.append(f"место в {round(s - fit.w / 2, 2)} м занято ({why}): сдвинуто на {abs(round(moved, 2))} м {'дальше' if moved > 0 else 'ближе к началу'} вдоль стены")
        fit.take(at, wall["angle"])
        out.append((at, wall["angle"]))
    return out


def _at_point(fit: Fitter, anchor: dict, notes: list[str]) -> list[tuple[XY, float]]:
    """One item at the asked point and angle; when it does not stand there, the nearest free place within
    SEARCH_RADIUS and why the asked one would not do."""
    at = (float(anchor["x"]), float(anchor["y"]))
    angle = float(anchor.get("angle") or 0)
    why = fit.blocker(at, angle)
    if why is None:
        fit.take(at, angle)
        return [((round(at[0], 3), round(at[1], 3)), angle)]
    near = fit.nearest(at, angle)
    if near is None:
        notes.append(f"в точке ({at[0]}, {at[1]}) не встаёт: {why}; свободного места в {SEARCH_RADIUS} м вокруг нет")
        return []
    notes.append(f"в точке ({at[0]}, {at[1]}) не встаёт: {why}; ближайшее свободное место — ({near[0]}, {near[1]}), в {round(math.dist(at, near), 2)} м")
    fit.take(near, angle)
    return [(near, angle)]


def _along_wall(fit: Fitter, room: Polygon, count: int, corners_only: bool = False, side: str | None = None) -> list[tuple[XY, float]]:
    """Backs to the walls: along each side of the room (or only the walls on `side`), or into its corners."""
    out: list[tuple[XY, float]] = []
    inset = room.buffer(-(fit.d / 2 + WALL_GAP), join_style=2)
    rings = [g for g in getattr(inset, "geoms", [inset]) if not g.is_empty]
    for ring in rings:
        ring = orient(ring, 1.0)
        pts = list(ring.exterior.coords)[:-1]
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            length = math.dist(a, b)
            if length < 1e-6:
                continue
            tx, ty = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            if side and side_of(tx, ty) != side:
                continue
            angle = facing(-ty, tx)
            first = max(fit.w / 2 - fit.d / 2, 0) + 0.005
            cands = [first] if corners_only else [first + k * (fit.w + fit.gap) for k in range(int((length - first + fit.w / 2) // (fit.w + fit.gap)) + 1)]
            for s in cands:
                if s > length + 1e-6:
                    break
                at = (round(a[0] + tx * s, 3), round(a[1] + ty * s, 3))
                if fit.fits(at, angle):
                    fit.take(at, angle)
                    out.append((at, angle))
                    if len(out) >= count:
                        return out
    return out


def _grid(fit: Fitter, room: Polygon, count: int, from_center: bool) -> list[tuple[XY, float]]:
    main, (cx, cy) = _frame(room)
    angle = round((main + 180) % 360, 2)
    (ux, uy), (fx, fy) = axes(angle)
    su, sf = fit.w + fit.gap, fit.d + fit.gap
    minx, miny, maxx, maxy = room.bounds
    reach = math.hypot(maxx - minx, maxy - miny)
    cands = []
    for i in range(-int(reach / su) - 1, int(reach / su) + 2):
        for j in range(-int(reach / sf) - 1, int(reach / sf) + 2):
            x, y = cx + ux * su * i + fx * sf * j, cy + uy * su * i + fy * sf * j
            if room.contains(Point(x, y)):
                cands.append((math.hypot(x - cx, y - cy) if from_center else (j, i), (round(x, 3), round(y, 3))))
    out: list[tuple[XY, float]] = []
    for _, at in sorted(cands):
        if fit.fits(at, angle):
            fit.take(at, angle)
            out.append((at, angle))
            if len(out) >= count:
                break
    return out


def _front_of(fit: Fitter, room: Polygon, anchor: dict, types: dict[str, dict], count: int) -> list[tuple[XY, float]]:
    """Items in a row before the anchor's front side, facing it (chairs at a desk, stools at a counter)."""
    at = anchor.get("x"), anchor.get("y")
    ta = types.get(anchor.get("type_id"))
    aw, ad, _ = size_of(ta)
    a_angle = float(anchor.get("angle") or 0)
    (ux, uy), (fx, fy) = axes(a_angle)
    facing_back = round((a_angle + 180) % 360, 2)                  # the items look at the anchor
    out: list[tuple[XY, float]] = []
    k = ad / 2 + fit.d / 2 + 0.1                                   # knee room between the anchor and the items
    span = fit.w + fit.gap
    for n in range(count):
        # from the middle outwards: 0, +1, −1, +2, −2 … of the anchor's width
        i = (n + 1) // 2 * (1 if n % 2 else -1)
        if n == 0:
            i = 0
        off = i * span
        if abs(off) + fit.w / 2 > aw / 2 + 0.3 and n > 0:
            break
        p = (round(at[0] + fx * k + ux * off, 3), round(at[1] + fy * k + uy * off, 3))
        if fit.fits(p, facing_back):
            fit.take(p, facing_back)
            out.append((p, facing_back))
    return out


def _even(fit: Fitter, room: Polygon, count: int) -> list[tuple[XY, float]]:
    """`count` places spread evenly over the room (lights, detectors, cameras under the ceiling): rows and columns
    by the room's proportions in its own frame, each item in the middle of its cell; a cell outside the outline
    (an L-shaped room) is left out and the gap filled by the farthest free point."""
    main, _ = _frame(room)
    angle = round((main + 180) % 360, 2)
    (ux, uy), (fx, fy) = axes(angle)
    pts = list(room.exterior.coords)
    us = [p[0] * ux + p[1] * uy for p in pts]
    vs = [p[0] * fx + p[1] * fy for p in pts]
    u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
    width, depth = max(u1 - u0, 0.1), max(v1 - v0, 0.1)
    cols = max(1, min(count, round(math.sqrt(count * width / depth)) or 1))
    rows = max(1, math.ceil(count / cols))
    while cols * rows < count:
        cols += 1
    cands: list[XY] = []
    for j in range(rows):
        for i in range(cols):
            u = u0 + width * (i + 0.5) / cols
            v = v0 + depth * (j + 0.5) / rows
            cands.append((round(u * ux + v * fx, 3), round(u * uy + v * fy, 3)))
    out: list[tuple[XY, float]] = []
    for at in cands:
        if len(out) >= count:
            break
        if room.contains(Point(at)) and fit.fits(at, angle):
            fit.take(at, angle)
            out.append((at, angle))
    if len(out) < count:
        for at in spread(room, [p for p, _ in out], count - len(out), max(0.5, math.sqrt(room.area / max(count, 1)) * 0.7)):
            if fit.fits(at, angle):
                fit.take(at, angle)
                out.append((at, angle))
    return out


def _label(a: dict, types: dict[str, dict]) -> str:
    t = types.get(a.get("type_id")) or {}
    return " ".join(x for x in (a.get("type_name") or t.get("name") or "предмет", a.get("inventory_no")) if x)


def hard_things(plan: dict, high: bool, on_wall: bool) -> list[tuple[Polygon, str]]:
    """What an item of this kind may not cross: partitions and columns, the door ways (unless it hangs high),
    and — for a wall-mounted thing — the openings with a margin."""
    solids, doors = obstacles(plan)
    hard = [(g, "стоит на перегородке или колонне") for g in solids]
    if not high:
        hard += [(g, "мешает двери или проходу") for g in doors]
    if on_wall:
        hard += [(o.buffer(0.3), "висит над дверью или окном") for o in openings(plan)]
    return hard


def place_in_room(room: Polygon, plan: dict, floor_assets: list[dict], types: dict[str, dict], t: dict,
                  count: int, where: str, gap: float, anchor: dict | None = None,
                  side: str | None = None, along=None, from_end: bool = False) -> tuple[list[tuple[XY, float]], list[str]]:
    """Places for `count` items of type `t` in the room: ([(at, angle)], notes). A wall-mounted thing goes along the
    walls whatever is asked, never over a door or a window; `front_of` puts the items before the anchor object."""
    if where not in WHERE:
        raise PlanError(f"where: {', '.join(WHERE)}")
    if not 1 <= count <= MAX_ITEMS:
        raise PlanError(f"count: от 1 до {MAX_ITEMS}")
    w, d, _ = size_of(t)
    high, on_wall = is_high(t), is_wall_mounted(t)
    taken = [(fp, _label(a, types)) for a, fp, h in standing(floor_assets, types) if h == high or on_wall]
    notes = []
    if on_wall:
        if where not in ("along_wall", "at_wall", "corners"):
            notes.append("настенный предмет: поставлен у стены")
            where = "along_wall"
    fit = Fitter(room, taken, hard_things(plan, high, on_wall), w, d, max(gap, 0.0))
    if where == "at_wall":
        if not side:
            raise PlanError("at_wall: укажите side (north/south/east/west) и along (метры от начала стены или start/middle/end)")
        places = _at_wall(fit, room, count, side, along if along is not None else "middle", notes, from_end)
    elif where == "at_point":
        if not anchor or anchor.get("x") is None:
            raise PlanError("at_point: нужна точка anchor {x, y, angle}")
        places = _at_point(fit, anchor, notes)
    elif where == "front_of":
        if not anchor or anchor.get("x") is None:
            raise PlanError("front_of: нужен объект-опора (anchor) с местом на плане")
        places = _front_of(fit, room, anchor, types, count)
    elif where == "along_wall":
        places = _along_wall(fit, room, count, side=side)
    elif where == "corners":
        places = _along_wall(fit, room, count, corners_only=True, side=side)
    elif high:
        places = _even(fit, room, count)                       # under the ceiling: spread over the whole room
    else:
        places = _grid(fit, room, count, from_center=where == "center")
    if len(places) < count and where not in ("at_wall", "at_point"):
        notes.append(f"поместилось {len(places)} из {count}: " + ("перед объектом-опорой нет места" if where == "front_of"
                     else "в помещении нет места" + ((f" у стены {side}" if side else " у стен") if where in ("along_wall", "corners") else "")))
    return places, notes


# ---------------------------------------------------------- layout check ---
def check_layout(rooms: list[dict], plan: dict, floor_assets: list[dict], types: dict[str, dict],
                 places: list[dict], moves: list[dict]) -> dict:
    """A layout someone has in mind, before it is proposed: for each new item ({type_id, x, y, angle, room_id?})
    and each move ({asset_id, x, y, angle?}) — which room it lands in, what is wrong (out of the rooms, through a
    partition, in a door way, on another item, a wall thing off the wall or over an opening), the wall it stands
    at and what it faces, and the nearest free place when the asked one will not do. Nothing is placed."""
    moved = {m.get("asset_id") for m in moves}
    by_id = {a["id"]: a for a in floor_assets if a.get("id")}
    kept = [a for a in floor_assets if a.get("id") not in moved]
    low_items = [(a, fp) for a, fp, h in standing(kept, types) if not h]
    fitters: dict[tuple[str, bool, bool], Fitter] = {}

    def fitter(room: dict, high: bool, on_wall: bool, w: float, d: float) -> Fitter:
        key = (room["id"], high, on_wall)
        if key not in fitters:
            taken = [(fp, _label(a, types)) for a, fp, h in standing(kept, types) if h == high or on_wall]
            fitters[key] = Fitter(room["poly"], taken, hard_things(plan, high, on_wall), w, d, 0.0)
        f = fitters[key]
        f.w, f.d = w, d
        return f

    wanted = []
    for i, pl in enumerate(places):
        t = types.get(pl.get("type_id"))
        wanted.append({"i": i, "what": (t or {}).get("name") or "предмет", "type": t, "at": (float(pl["x"]), float(pl["y"])),
                       "angle": float(pl.get("angle") or 0), "room_id": pl.get("room_id"), "elevation": None})
    for m in moves:
        a = by_id.get(m.get("asset_id")) or {}
        t = types.get(a.get("type_id"))
        wanted.append({"i": len(wanted), "what": _label(a, types) if a else "объект", "type": t, "at": (float(m["x"]), float(m["y"])),
                       "angle": float(m.get("angle") if m.get("angle") is not None else a.get("angle") or 0), "room_id": m.get("room_id"),
                       "elevation": a.get("elevation")})
    out, placed_low = [], list(low_items)
    for w_ in wanted:
        t, at, angle = w_["type"], w_["at"], w_["angle"]
        w, d, _ = size_of(t)
        high, on_wall = is_high(t, w_["elevation"]), is_wall_mounted(t)
        fp = footprint(at, angle, w, d)
        room = next((r for r in rooms if r["poly"].buffer(0.05).contains(Point(at))), None)
        asked = next((r for r in rooms if r["id"] == w_["room_id"]), None) if w_["room_id"] else None
        problems, fix = [], None
        if room is None:
            problems.append("вне помещений")
        elif asked is not None and asked["id"] != room["id"]:
            problems.append(f"не в том помещении: попадает в «{room['name'] or 'без названия'}»")
        target = asked or room
        wall = None
        if target is not None:
            f = fitter(target, high, on_wall, w, d)
            why = f.blocker(at, angle) if room is target else f.blocker(at, angle) or "выходит за контур помещения"
            if why:
                problems.append(why)
            near = f.nearest(at, angle) if problems else None
            if near and near != (round(at[0], 3), round(at[1], 3)):
                fix = [near[0], near[1]]
            f.take(near if (near and problems) else at, angle, w_["what"])
            walls = walls_of(target["poly"])
            if walls:
                nearest_wall = min(walls, key=lambda ww: LineString([ww["from"], ww["to"]]).distance(Point(at)))
                dist = LineString([nearest_wall["from"], nearest_wall["to"]]).distance(Point(at))
                if dist <= 1.0:
                    wall = f"{nearest_wall['side']} {round(dist, 2)} м" + ("" if abs((angle - nearest_wall["angle"]) % 360) < 1 else ", не спиной к ней")
                if on_wall and dist > 0.3:
                    problems.append("настенный предмет не на стене")
        faces = None
        if not high:
            _, (fx, fy) = axes(angle)
            best = None
            for a, fp2 in placed_low:
                c = fp2.centroid
                dx, dy = c.x - at[0], c.y - at[1]
                dd = math.hypot(dx, dy)
                if 0.05 < dd <= 1.5 and (dx * fx + dy * fy) / dd > 0.5 and (best is None or dd < best[0]):
                    best = (dd, _label(a, types))
            faces = best[1] if best else None
            placed_low.append(({"type_name": w_["what"], "type_id": (t or {}).get("id")}, fp))
        out.append({"i": w_["i"], "what": w_["what"], "at": [round(at[0], 2), round(at[1], 2)], "angle": angle,
                    "room": {"id": room["id"], "name": room["name"]} if room else None,
                    "problems": problems, "wall": wall, "faces": faces, **({"fix": fix} if fix else {})})
    bad = sum(1 for x in out if x["problems"])
    return {"ok": bad == 0, "problems": bad, "items": out}


# ------------------------------------------------------------ detectors ---
def detectors_needed(area: float, radius: float) -> int:
    return max(1, math.ceil(area / (0.7 * math.pi * radius ** 2)))


def spread(poly: Polygon, have: list[XY], n: int, step: float) -> list[XY]:
    inner = poly.buffer(-0.5)
    inner = inner if not inner.is_empty else poly
    minx, miny, maxx, maxy = inner.bounds
    cands = [(minx + step / 2 + i * step, miny + step / 2 + j * step)
             for i in range(int((maxx - minx) / step) + 1) for j in range(int((maxy - miny) / step) + 1)]
    cands = [c for c in cands if inner.contains(Point(c))] or [inner.representative_point().coords[0]]
    chosen: list[XY] = []
    for _ in range(n):
        ref = have + chosen
        best = max(cands, key=lambda c: min((math.dist(c, h) for h in ref), default=0.0) if ref else -math.dist(c, inner.centroid.coords[0]))
        chosen.append(best)
        cands = [c for c in cands if c != best] or cands
    return [(round(x, 2), round(y, 2)) for x, y in chosen]


def detectors_in_room(room: Polygon, floor_assets: list[dict], types: dict[str, dict], radius: float) -> dict:
    """How many detectors the room has (any type with a detect_radius standing in it), needs, and where to add."""
    have = [(a["x"], a["y"]) for a in floor_assets if a.get("x") is not None and value(types.get(a.get("type_id")), "detect_radius")
            and room.buffer(0.05).contains(Point(a["x"], a["y"]))]
    need = detectors_needed(room.area, radius)
    add = spread(room, have, max(0, need - len(have)), radius * math.sqrt(2) * 0.9) if len(have) < need else []
    return {"area": round(room.area, 1), "has": len(have), "need": need, "add": add}


# -------------------------------------------------------------- cameras ---
def sector(apex, angle: float, fov: float, r: float) -> Polygon:
    _, (fx, fy) = axes(angle)
    if fov >= 360:
        return Point(apex).buffer(r, 64)
    a0 = math.atan2(fy, fx) - math.radians(fov) / 2
    n = max(8, int(fov))
    pts = [tuple(apex)] + [(apex[0] + r * math.cos(a0 + math.radians(fov) * i / n), apex[1] + r * math.sin(a0 + math.radians(fov) * i / n)) for i in range(n + 1)]
    return Polygon(pts)


def camera_params(a: dict, t: dict | None) -> tuple[float, float, float] | None:
    fov = value(t, "cam_fov")
    if fov is None:
        return None
    rng = value(t, "cam_range") or 10.0
    ident = min(rng, value(t, "cam_ident") or rng)
    return fov, rng, ident


def cameras_in_rooms(rooms: list[dict], floor_assets: list[dict], types: dict[str, dict]) -> list[dict]:
    cams = [(a, prm) for a in floor_assets if a.get("x") is not None and (prm := camera_params(a, types.get(a.get("type_id")))) is not None]
    out = []
    for r in rooms:
        poly = r["poly"]
        mine = [(a, prm) for a, prm in cams if poly.buffer(0.05).contains(Point(a["x"], a["y"]))]
        seen = unary_union([sector((a["x"], a["y"]), float(a.get("angle") or 0), prm[0], prm[1]).intersection(poly) for a, prm in mine]) if mine else Polygon()
        ident = unary_union([sector((a["x"], a["y"]), float(a.get("angle") or 0), prm[0], prm[2]).intersection(poly) for a, prm in mine]) if mine else Polygon()
        gaps = poly.difference(seen)
        parts = sorted(getattr(gaps, "geoms", [gaps]), key=lambda g: -g.area)
        area = poly.area or 1.0
        out.append({"room_id": r["id"], "name": r["name"], "area": round(poly.area, 2), "cameras": [a["id"] for a, _ in mine],
                    "seen": round(seen.area / area * 100, 1), "identify": round(ident.area / area * 100, 1),
                    "unseen": [{"area": round(g.area, 2), "bbox": [round(v, 2) for v in g.bounds]} for g in parts[:3] if g.area >= 0.5]})
    return out


# -------------------------------------------------------------- checks ---
def check_floor(rooms: list[dict], room_types: dict[str, str], plan: dict, floor_assets: list[dict], types: dict[str, dict], limit: int = 50) -> dict:
    """blocked — items in door ways, on partitions or columns, on each other, out of the walls; cameras — rooms poorly
    seen (when the floor has cameras); empty — rooms meant for use with nothing in them; doors — narrower than 80 cm."""
    solids, doors = obstacles(plan)
    name = {r["id"]: r["name"] or "без названия" for r in rooms}
    low = [(a, fp) for a, fp, high in standing(floor_assets, types) if not high]
    blocked = []
    for i, (a, fp) in enumerate(low):
        why = []
        if any(fp.intersection(g).area > 0.01 for g in doors):
            why.append("мешает двери или проходу")
        if any(fp.intersection(g).area > 0.01 for g in solids):
            why.append("стоит на перегородке или колонне")
        others = [f"{b.get('type_name') or ''} {b.get('inventory_no') or ''}".strip() for b, fp2 in low[i + 1:] if fp.intersection(fp2).area > 0.01]
        if others:
            why.append("налезает на " + ", ".join(others[:3]))
        if rooms and not any(r["poly"].buffer(0.05).contains(fp) for r in rooms):
            why.append("выходит за стены помещения")
        if why:
            blocked.append({"asset_id": a["id"], "name": f"{a.get('type_name') or ''} {a.get('inventory_no') or ''}".strip(),
                            "room_id": a.get("room_id"), "room": name.get(a.get("room_id"), ""), "at": [round(a["x"], 2), round(a["y"], 2)], "problems": why})
    cams = [c for c in cameras_in_rooms(rooms, floor_assets, types) if c["seen"] < 50 and room_types.get(c["room_id"], "other") not in NO_CAMERAS_NEEDED] \
        if any(camera_params(a, types.get(a.get("type_id"))) for a in floor_assets) else []
    used = {a.get("room_id") for a in floor_assets}
    empty = [{"room_id": r["id"], "name": name[r["id"]], "type": room_types.get(r["id"]), "area": round(r["poly"].area, 1)}
             for r in rooms if r["id"] not in used and (room_types.get(r["id"]) or "other") not in NOT_FURNISHED]
    narrow = [{"center": o.get("center"), "width": o.get("width")} for o in plan.get("openings") or []
              if o.get("kind") == "door" and (o.get("width") or 1) < NARROW_DOOR]
    out = {"blocked": blocked[:limit], "cameras": cams[:limit], "empty": empty[:limit], "doors": narrow[:limit]}
    return out | {"counts": {k: len(v) for k, v in (("blocked", blocked), ("cameras", cams), ("empty", empty), ("doors", narrow))}}


def line_crosses(a: XY, b: XY, faces) -> int:
    seg = LineString([a, b])
    return sum(1 for f in faces if seg.intersects(f))
