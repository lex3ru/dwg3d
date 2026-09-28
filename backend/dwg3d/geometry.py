"""2D plan reconstruction (meters): walls, columns, openings, rooms, slab.

Wall reconstruction strategy
----------------------------
1. All wall-layer linework is noded (split at intersections) on a 1 mm grid.
2. Small gaps are closed: dangling endpoints are joined to a nearby node
   (snap_tolerance) or extended along their direction until they hit other
   linework (gap_tolerance).
3. The linework is polygonized. Faces that are *thin* everywhere (erode to
   nothing at max_wall_thickness/2) are wall material; wide faces are rooms.
   Double-line walls, sandwich walls split by an axis/insulation line, and
   walls drawn as closed outlines all end up as one unioned wall mass, so
   nothing is doubled.
4. Linework that didn't become part of a wall face is paired: two parallel
   lines within wall thickness form a wall strip (unclosed double walls);
   a lone line far from any wall is a single-line wall -> buffered by
   default_wall_thickness.

Openings
--------
* Gap openings: wall "end caps" (short edge between two antiparallel edges)
  are ray-cast outward. If the rays hit wall material at a consistent
  distance, the gap between is an opening; window-layer linework inside the
  gap makes it a window, otherwise a door (or a passage if too wide).
* Block openings: door/window INSERTs sitting on a continuous wall cut the
  wall (the 2.5D equivalent of a boolean subtract).
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import math
import re
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from .config import LayerMapper
from .features import DoorArc, detect_door_arcs, detect_stairs
from .floors import parse_mark

log = logging.getLogger(__name__)
EMPTY = Polygon()


@dataclass
class Opening:
    kind: str                     # door | window | passage
    poly: Polygon                 # footprint through the wall (the gap)
    width: float
    center: tuple[float, float]
    direction: tuple[float, float]  # unit vector along the wall
    source: str                   # gap | block | manual
    depth: float = 0.0            # wall thickness at the opening
    leaves: list = field(default_factory=list)   # door leaves: [(hinge_xy, tip_xy)]

    @property
    def id(self) -> str:
        return f"o{round(self.center[0] * 100)}_{round(self.center[1] * 100)}"


@dataclass
class Room:
    poly: Polygon
    name: str = ""
    area: float = 0.0


@dataclass
class FloorPlan:
    walls: Polygon | MultiPolygon = EMPTY          # full-height wall mass (openings cut)
    wall_parts: dict = field(default_factory=dict)  # "wall" | "partition" -> geometry
    stairs: list = field(default_factory=list)
    columns: Polygon | MultiPolygon = EMPTY
    openings: list[Opening] = field(default_factory=list)
    rooms: list[Room] = field(default_factory=list)
    footprint: Polygon | MultiPolygon = EMPTY
    stats: dict = field(default_factory=dict)
    debug: dict = field(default_factory=dict)      # extra geometry for plots


# ---------------------------------------------------------------- helpers --
def _polys(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon) and not p.is_empty] + \
        [q for p in getattr(g, "geoms", []) if not isinstance(p, Polygon) for q in _polys(p)]


def _mp(polys):
    polys = [p for p in polys if p is not None and not p.is_empty]
    if not polys:
        return EMPTY
    u = unary_union(polys)
    ps = _polys(u)
    return ps[0] if len(ps) == 1 else MultiPolygon(ps)


def _unit(v):
    n = math.hypot(v[0], v[1])
    return (v[0] / n, v[1] / n) if n > 1e-12 else (0.0, 0.0)


def is_thin(poly: Polygon, max_t: float) -> bool:
    return poly.buffer(-max_t / 2, join_style="mitre").is_empty


def _segments(line: LineString):
    c = np.asarray(line.coords)
    return [(c[i], c[i + 1]) for i in range(len(c) - 1) if np.hypot(*(c[i + 1] - c[i])) > 1e-6]


# ------------------------------------------------------------- linework ---
def close_gaps(lines: list[LineString], snap: float, gap: float) -> tuple[list[LineString], int]:
    """Node linework and add short connector segments at dangling ends."""
    if not lines:
        return [], 0
    grid = 0.001
    noded = unary_union(shapely.set_precision(shapely.MultiLineString(
        [np.asarray(l.coords) for l in lines]), grid))
    segs = [g for g in getattr(noded, "geoms", [noded]) if isinstance(g, LineString) and g.length > 0]
    deg = collections.Counter()
    for s in segs:
        c = s.coords
        deg[tuple(np.round(c[0], 3))] += 1
        deg[tuple(np.round(c[-1], 3))] += 1
    nodes = np.array(list(deg.keys()))
    node_tree = STRtree([Point(p) for p in nodes]) if len(nodes) else None
    seg_tree = STRtree(segs)
    connectors = []
    for si, s in enumerate(segs):
        c = np.asarray(s.coords)
        for end, prev in ((c[-1], c[-2]), (c[0], c[1])):
            key = tuple(np.round(end, 3))
            if deg[key] != 1:
                continue
            p = Point(end)
            # (a) join to a nearby node
            best = None
            for j in node_tree.query(p.buffer(snap)):
                q = nodes[j]
                dist = math.dist(q, end)
                if 1e-6 < dist <= snap and (best is None or dist < best[0]):
                    best = (dist, q)
            if best:
                connectors.append(LineString([end, best[1]]))
                continue
            # (b) extend along the segment direction
            dvec = _unit(end - prev)
            ray = LineString([end + np.array(dvec) * 1e-4, end + np.array(dvec) * gap])
            hit = None
            for j in seg_tree.query(ray):
                if j == si:
                    continue
                x = ray.intersection(segs[j])
                if not x.is_empty:
                    dist = p.distance(x)
                    if hit is None or dist < hit[0]:
                        hit = (dist, x)
            if hit:
                q = shapely.ops.nearest_points(p, hit[1])[1]
                connectors.append(LineString([end, (q.x, q.y)]))
                continue
            # (c) perpendicular snap onto nearby linework
            for j in seg_tree.query(p.buffer(snap)):
                if j == si:
                    continue
                if segs[j].distance(p) <= snap:
                    q = shapely.ops.nearest_points(p, segs[j])[1]
                    if q.distance(p) > 1e-6:
                        connectors.append(LineString([end, (q.x, q.y)]))
                    break
    if connectors:
        allg = unary_union(shapely.set_precision(shapely.MultiLineString(
            [np.asarray(l.coords) for l in segs + connectors]), grid))
        segs = [g for g in getattr(allg, "geoms", [allg]) if isinstance(g, LineString) and g.length > 0]
    return segs, len(connectors)


def pair_leftovers(segs, min_t, max_t, default_t, walls: Polygon | MultiPolygon):
    """Leftover linework -> wall strips (parallel pairs) / single-line walls."""
    pieces = []
    for s in segs:
        for a, b in _segments(s):
            if np.hypot(*(b - a)) >= 0.05:
                pieces.append((a, b))
    if not pieces:
        return [], [], 0
    geoms = [LineString(p) for p in pieces]
    tree = STRtree(geoms)
    paired = set()
    quads = []
    for i, (a, b) in enumerate(pieces):
        u = np.array(_unit(b - a))
        n = np.array((-u[1], u[0]))
        for j in tree.query(geoms[i].buffer(max_t)):
            if j <= i:
                continue
            c, d = pieces[j]
            v = np.array(_unit(d - c))
            if abs(float(np.dot(u, v))) < math.cos(math.radians(3)):
                continue
            dist = float(np.dot(c - a, n))
            if not (min_t <= abs(dist) <= max_t):
                continue
            t0, t1 = sorted((0.0, float(np.dot(b - a, u))))
            s0, s1 = sorted((float(np.dot(c - a, u)), float(np.dot(d - a, u))))
            lo, hi = max(t0, s0), min(t1, s1)
            if hi - lo < max(0.1, abs(dist)):
                continue
            quad = Polygon([a + u * lo, a + u * hi, a + u * hi + n * dist, a + u * lo + n * dist])
            quads.append((quad, (a + b) / 2))
            paired.update((i, j))
    singles = []
    near = walls.buffer(max_t) if not walls.is_empty else EMPTY
    for i, g in enumerate(geoms):
        if i in paired:
            continue
        if not near.is_empty and near.contains(g):
            continue
        if g.length < 0.3:
            continue
        singles.append((g.buffer(default_t / 2, cap_style="flat", join_style="mitre"), np.asarray(g.centroid.coords[0])))
    return quads, singles, len(paired)


# ------------------------------------------------------------- openings ---
def _end_caps(solid, min_t, max_t):
    """Yield (a, b, outward_normal, wall_dir) for wall end caps."""
    for poly in _polys(solid):
        poly = orient(poly.simplify(0.004), 1.0)
        for ring in [poly.exterior, *poly.interiors]:
            c = np.asarray(ring.coords)[:-1]
            n = len(c)
            if n < 4:
                continue
            for k in range(n):
                p0, p1, p2, p3 = c[k - 1], c[k], c[(k + 1) % n], c[(k + 2) % n]
                L = math.dist(p1, p2)
                if not (min_t * 0.8 <= L <= max_t * 1.05):
                    continue
                dp, dn, dc = _unit(p1 - p0), _unit(p3 - p2), _unit(p2 - p1)
                if math.dist(p0, p1) < 0.05 or math.dist(p2, p3) < 0.05:
                    continue
                if np.dot(dp, dn) > -math.cos(math.radians(12)):
                    continue  # side edges must be antiparallel
                if abs(np.dot(dp, dc)) > 0.2 or abs(np.dot(dn, dc)) > 0.2:
                    continue
                out = np.array((dc[1], -dc[0]))  # right-hand normal = outward
                if np.dot(out, dp) < 0.9:
                    continue
                yield p1, p2, out, np.array(dp)


def _arc_leaves(rect: Polygon, width: float, arcs: list[DoorArc]):
    """Door swing arcs whose hinge sits at this opening -> leaves [(hinge, tip)]."""
    leaves = []
    for a in arcs:
        if rect.distance(Point(a.center)) > 0.15:
            continue
        if not (0.35 * width <= a.r <= 1.2 * width):
            continue
        # the open leaf is the arc end that lies away from the opening line
        p0, p1 = Point(a.p0), Point(a.p1)
        tip = a.p0 if rect.distance(p0) > rect.distance(p1) else a.p1
        leaves.append((a.center, tip))
    return leaves[:2]


def gap_openings(walls, solid, windows_geom, door_geom, g, arcs=()) -> list[Opening]:
    min_t, max_t = g["min_wall_thickness"], g["max_wall_thickness"]
    min_w, max_door, max_win = g["min_opening_width"], g["max_door_width"], g["max_window_width"]
    parts = _polys(solid)
    if not parts:
        return []
    tree = STRtree(parts)
    shapely.prepare(solid)
    win_tree = STRtree(windows_geom) if windows_geom else None
    door_tree = STRtree(door_geom) if door_geom else None
    found: list[Opening] = []

    def classify(rect, d, facing_cap):
        inner = rect.buffer(-0.005)
        has_win = bool(win_tree is not None and len(win_tree.query(inner, predicate="intersects")))
        has_door = bool(door_tree is not None and len(door_tree.query(rect.buffer(0.3), predicate="intersects")))
        has_door = has_door or bool(_arc_leaves(rect, d, arcs))
        if has_win and d <= max_win:
            return "window"
        if d <= max_door and (facing_cap or has_door or d <= max_door * 0.6):
            return "door"
        if has_door and d <= max_door * 1.3:
            return "door"
        if facing_cap and d <= max_win:
            return "passage"
        return None

    caps = list(_end_caps(walls, min_t, max_t))
    # (1) pairs of wall ends facing each other (works for curved walls too)
    mids = np.array([(a + b) / 2 for a, b, _, _ in caps]) if caps else np.zeros((0, 2))
    for i, (a, b, out, _) in enumerate(caps):
        for j in range(i + 1, len(caps)):
            c, dd, out2, _ = caps[j]
            v = mids[j] - mids[i]
            dist = float(np.hypot(*v))
            if not (min_w <= dist <= max_win):
                continue
            vu = v / dist
            if np.dot(out, out2) > -0.9 or np.dot(vu, out) < 0.96 or np.dot(-vu, out2) < 0.96:
                continue
            La, Lc = math.dist(a, b), math.dist(c, dd)
            if not (0.7 <= La / Lc <= 1.4):
                continue
            quad = shapely.MultiPoint([a, b, c, dd]).convex_hull
            if not isinstance(quad, Polygon) or quad.area > 1.25 * dist * max(La, Lc):
                continue
            if quad.buffer(-0.01).intersection(solid).area > 0.02 * quad.area:
                continue
            kind = classify(quad, dist, True)
            if kind:
                m = (mids[i] + mids[j]) / 2
                t = np.array(_unit(v))
                found.append(Opening(kind, quad, dist, (float(m[0]), float(m[1])), (float(t[0]), float(t[1])),
                                     "gap", (La + Lc) / 2))
    # (2) straight rays from each wall end (cap -> opposite cap or wall face)
    for a, b, out, wdir in caps:
        L = math.dist(a, b)
        dists = []
        for f in (0.1, 0.3, 0.5, 0.7, 0.9):
            s = a + (b - a) * f + out * 1e-3
            ray = LineString([s, s + out * max_win])
            best = None
            for j in tree.query(ray):
                x = ray.intersection(parts[j])
                if not x.is_empty:
                    dd = Point(s).distance(x)
                    best = dd if best is None else min(best, dd)
            dists.append(best)
        if any(d is None for d in dists):
            continue
        d = min(dists)
        if max(dists) - d > max(0.03, 0.2 * L) or d < min_w:
            continue
        rect = Polygon([a, b, b + out * d, a + out * d])
        mid = (a + b) / 2
        # facing another wall end (collinear continuation) or a wall face?
        u = np.array(_unit(b - a))
        probe = mid + out * (d + 0.03)
        side = L / 2 + 0.08
        facing_cap = not solid.contains(Point(probe + u * side)) and not solid.contains(Point(probe - u * side))
        kind = classify(rect, d, facing_cap)
        if not kind:
            continue
        found.append(Opening(kind, rect, d, (float(mid[0] + out[0] * d / 2), float(mid[1] + out[1] * d / 2)),
                             (float(out[0]), float(out[1])), "gap", L))
    return _dedupe(found)


def _dedupe(ops: list[Opening]) -> list[Opening]:
    rank = {"window": 0, "vitrage": 0, "door": 1, "passage": 2}
    ops = sorted(ops, key=lambda o: (rank[o.kind], o.width))
    kept: list[Opening] = []
    tree_polys: list[Polygon] = []
    for o in ops:
        dup = False
        for k, p in zip(kept, tree_polys):
            inter = o.poly.intersection(p).area
            if inter > 0.3 * min(o.poly.area, p.area):
                dup = True
                break
        if not dup:
            kept.append(o)
            tree_polys.append(o.poly)
    return kept


def block_openings(inserts, walls, g) -> list[Opening]:
    """Door/window INSERTs: cut a rectangle through the wall they sit on."""
    max_t = g["max_wall_thickness"]
    out = []
    if walls.is_empty:
        return out
    boundary_segs = []
    for p in _polys(walls):
        for ring in [p.exterior, *p.interiors]:
            boundary_segs += _segments(LineString(ring.coords))
    seg_geoms = [LineString(s) for s in boundary_segs]
    tree = STRtree(seg_geoms) if seg_geoms else None
    for ins in inserts:
        pts = ins.pts
        hull = shapely.MultiPoint(pts).convex_hull if len(pts) > 2 else Point(ins.x, ins.y).buffer(0.3)
        # dominant wall direction near the insert (length-weighted, angle mod 180)
        acc = np.zeros(2)
        for j in tree.query(hull.buffer(max_t)):
            a, b = boundary_segs[j]
            v = b - a
            ang = 2 * math.atan2(v[1], v[0])
            acc += np.hypot(*v) * np.array((math.cos(ang), math.sin(ang)))
        if not acc.any():
            continue
        th = math.atan2(acc[1], acc[0]) / 2
        u = np.array((math.cos(th), math.sin(th)))
        n = np.array((-u[1], u[0]))
        o = np.array((ins.x, ins.y))
        proj = (pts - o) @ u
        a0, a1 = float(proj.min()), float(proj.max())
        if a1 - a0 < 0.3:
            continue
        # wall band across the opening: probe the jambs just outside the opening
        probe = Polygon([o + u * (a0 - 0.3) - n * max_t, o + u * (a1 + 0.3) - n * max_t,
                         o + u * (a1 + 0.3) + n * max_t, o + u * (a0 - 0.3) + n * max_t])
        jambs = [p for p in _polys(walls.intersection(probe)) if p.distance(Point(o)) < max_t]
        if not jambs:
            continue
        pn = np.vstack([np.asarray(p.exterior.coords) for p in jambs]) - o
        b0, b1 = float((pn @ n).min()), float((pn @ n).max())
        rect = Polygon([o + u * a0 + n * b0, o + u * a1 + n * b0, o + u * a1 + n * b1, o + u * a0 + n * b1])
        c = o + u * (a0 + a1) / 2 + n * (b0 + b1) / 2
        out.append(Opening(ins.role[:-1], rect, a1 - a0, (float(c[0]), float(c[1])),
                           (float(u[0]), float(u[1])), "block", b1 - b0))
    return out


# ---------------------------------------------------------------- rooms ---
_RE_NUMERIC = re.compile(r"^[\d\s.,+\-±×x*/=()мм²m2]*$", re.I)


def _footprint(solid, openings):
    """Building outline: close remaining gaps in the outer wall (morphological
    closing), then fill the interior. Uses the smallest closing radius whose
    filled area is close to what the largest radius gives."""
    base = _mp([solid] + [o.poly for o in openings])
    if base.is_empty:
        return EMPTY
    results = []
    for r in (0.05, 0.5, 1.0, 2.0, 3.5, 5.0):
        closed = base.buffer(r, quad_segs=4).buffer(-r, quad_segs=4)
        filled = _mp([Polygon(p.exterior) for p in _polys(closed)])
        results.append(filled)
    target = results[-1].area
    k = next(i for i, f in enumerate(results) if f.area >= 0.93 * target)
    if k <= 1:
        return _mp(_polys(results[k].simplify(0.01)))
    # large gaps: rounded closing makes blobby outlines; a concave hull of the
    # wall vertices bridges gaps with straight chords instead.
    pts = np.vstack([np.asarray(r.coords) for p in _polys(base) for r in [p.exterior]])
    mp = shapely.MultiPoint(pts)
    for ratio in (0.02, 0.05, 0.1, 0.2, 0.35):
        hull = shapely.concave_hull(mp, ratio=ratio)
        hull = _mp([hull, base])
        hull = _mp([Polygon(p.exterior) for p in _polys(hull)])
        if hull.area >= 0.93 * results[k].area:
            return hull
    return results[k]


def room_labels(texts, ignore=()):
    """Texts that can name a room: not elevation marks, numbers or door/window marks."""
    pats = [re.compile(p) for p in ignore or ()]
    return [t for t in texts if parse_mark(t.text) is None and not _RE_NUMERIC.match(t.text)
            and not any(p.search(t.text.strip()) for p in pats)]


def find_rooms(footprint, solid, openings, labels, min_area) -> list[Room]:
    space = footprint.difference(_mp([solid] + [o.poly for o in openings]))
    space = space.buffer(-0.02, join_style="mitre").buffer(0.02, join_style="mitre")
    rooms = []
    for p in sorted(_polys(space), key=lambda p: -p.area):
        if p.area < min_area:
            continue
        inside = [t for t in labels if p.contains(Point(t.x, t.y))]
        inside.sort(key=lambda t: (-t.height, len(t.text)))
        name = " ".join(inside[0].text.split())[:60] if inside else ""
        rooms.append(Room(p, name, round(p.area, 2)))
    return rooms


# ---------------------------------------------------------- categories ---
class _CatLookup:
    """Which wall category ("wall" / "partition") a piece of geometry came from,
    by looking up the original linework lying on it."""

    def __init__(self, lines: list[tuple[LineString, str]]):
        self.lines = lines
        self.tree = STRtree([l for l, _ in lines]) if lines else None

    def at(self, xy, tol=0.006) -> str | None:
        if self.tree is None:
            return None
        p = Point(xy)
        for j in self.tree.query(p.buffer(tol)):
            if self.lines[j][0].distance(p) <= tol:
                return self.lines[j][1]
        return None

    def of_polygon(self, poly: Polygon) -> str:
        votes = collections.Counter()
        for a, b in _segments(LineString(poly.exterior.coords)):
            c = self.at((a + b) / 2)
            if c:
                votes[c] += float(np.hypot(*(b - a)))
        return votes.most_common(1)[0][0] if votes else "wall"


def _opening_rect(o: Opening, extra_depth: float = 0.0) -> Polygon:
    """Opening footprint as an oriented rectangle, optionally deepened."""
    u = np.array(o.direction)
    n = np.array((-u[1], u[0]))
    c = np.array(o.center)
    hw, hd = o.width / 2, max(o.depth, 0.05) / 2 + extra_depth
    return Polygon([c - u * hw - n * hd, c + u * hw - n * hd, c + u * hw + n * hd, c - u * hw + n * hd])


# --------------------------------------------------------------- edits ---
def _seg_rect(a, b, width) -> Polygon:
    return LineString([a, b]).buffer(width / 2, cap_style="flat", join_style="mitre")


def _wall_band(walls, p, n, max_t):
    """Thickness interval of the wall at point p across direction n:
    (b0, b1) offsets along n, or None if p is not on/at a wall."""
    probe = LineString([p - n * max_t, p + n * max_t])
    best = None
    for piece in getattr(probe.intersection(walls), "geoms", [probe.intersection(walls)]):
        if piece.is_empty or piece.geom_type != "LineString":
            continue
        d = piece.distance(Point(p))
        if d <= 0.08 and (best is None or d < best[0]):
            c = np.asarray(piece.coords) - p
            t = c @ n
            best = (d, float(t.min()), float(t.max()))
    return best[1:] if best else None


def _opening_from_segment(a, b, kind, walls, max_t) -> Opening | None:
    """User drew a segment on/along a wall -> rectangle through the full wall
    thickness (measured with cross-sections), or None if not on a wall."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    u = np.array(_unit(b - a))
    if not u.any():
        return None
    n = np.array((-u[1], u[0]))
    # several cross-sections; the median rejects a section that runs along an
    # adjoining perpendicular wall (it would make the opening far too deep)
    bands = [_wall_band(walls, a + (b - a) * t, n, max_t) for t in (0.1, 0.3, 0.5, 0.7, 0.9)]
    bands = [x for x in bands if x]
    if not bands:
        return None
    b0 = float(np.median([x[0] for x in bands]))
    b1 = float(np.median([x[1] for x in bands]))
    if b1 - b0 < 0.03:
        return None
    w = math.dist(a, b)
    mid = (a + b) / 2
    rect = Polygon([mid - u * w / 2 + n * b0, mid + u * w / 2 + n * b0,
                    mid + u * w / 2 + n * b1, mid - u * w / 2 + n * b1])
    c = mid + n * (b0 + b1) / 2
    return Opening(kind, rect, w, (float(c[0]), float(c[1])), (float(u[0]), float(u[1])), "manual", b1 - b0)


def _extend_to_walls(a, b, walls, reach=0.6):
    """Extend a manually drawn wall's ends to meet existing walls within
    `reach` (a sloppy end short of a wall would otherwise leave a gap)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    u = np.array(_unit(b - a))
    if walls.is_empty or not u.any():
        return a, b
    out = []
    for p, d in ((a, -u), (b, u)):
        if walls.contains(Point(p)):
            out.append(p)
            continue
        ray = LineString([p, p + d * reach])
        x = ray.intersection(walls)
        if x.is_empty:
            out.append(p)
        else:
            q = shapely.ops.nearest_points(Point(p), x)[1]
            out.append(np.array((q.x, q.y)) + d * 0.02)
    return out[0], out[1]


def _find_opening(openings, at, tol=0.4):
    p = Point(at)
    best = None
    for o in openings:
        d = o.poly.distance(p)
        if d <= tol and (best is None or d < best[0]):
            best = (d, o)
    return best[1] if best else None


# ----------------------------------------------------------------- main ---
def build_plan(shapes, texts, inserts, cfg, offset=(0.0, 0.0), edits: dict | None = None) -> FloorPlan:
    g = cfg["geometry"]
    b = cfg.get("building", {})
    edits = edits or {}
    mapper = LayerMapper(cfg)
    min_t, max_t = g["min_wall_thickness"], g["max_wall_thickness"]
    ox, oy = offset
    sh = np.array([ox, oy])
    plan = FloorPlan()

    def shift(s):
        arc = (s.arc[0] + ox, s.arc[1] + oy, *s.arc[2:]) if s.arc else None
        return dataclasses.replace(s, pts=s.pts + sh, arc=arc)

    shapes = [shift(s) for s in shapes]
    texts = [dataclasses.replace(t, x=t.x + ox, y=t.y + oy) for t in texts]
    inserts = [dataclasses.replace(i, pts=i.pts + sh, x=i.x + ox, y=i.y + oy) for i in inserts]

    # --- stairs & door arcs (from raw linework, before walls)
    stairs, used = (detect_stairs(shapes, g) if g.get("detect_stairs", True) else ([], set()))
    arcs = detect_door_arcs(shapes, g)

    wall_lines, wall_fills, col_polys, col_lines = [], [], [], []
    win_geoms, door_geoms, room_polys, ins_polys, ins_lines, vit_geoms = [], [], [], [], [], []
    for i, s in enumerate(shapes):
        if i in used:
            continue
        pts = s.pts
        if s.closed and len(pts) >= 3 and not np.allclose(pts[0], pts[-1]):
            pts = np.vstack([pts, pts[:1]])
        fill = s.kind in ("HATCH", "SOLID", "TRACE")
        if s.role == "walls":
            cat = "partition" if mapper.is_partition(s.layer) else "wall"
            if fill:
                p = Polygon(pts).buffer(0)
                if not p.is_empty:
                    wall_fills.append((p, cat))
            else:
                wall_lines.append((LineString(pts), cat))
        elif s.role == "columns":
            if s.closed and len(pts) >= 4:
                p = Polygon(pts).buffer(0)
                if p.area > 1e-4:
                    col_polys.append(p)
            else:
                col_lines.append(LineString(pts))
        elif s.role == "windows":
            win_geoms.append(LineString(pts) if len(pts) >= 2 else Point(pts[0]))
            if mapper.is_vitrage(s.layer):
                vit_geoms.append(win_geoms[-1])
        elif s.role == "doors":
            door_geoms.append(LineString(pts))
        elif s.role == "insulation":
            if fill or (s.closed and len(pts) >= 4):
                p = Polygon(pts).buffer(0)
                if p.area > 1e-4:
                    ins_polys.append(p)
            else:
                ins_lines.append(LineString(pts))
        elif s.role == "rooms" and s.closed and len(pts) >= 4:
            p = Polygon(pts).buffer(0)
            if p.area >= g["min_room_area"]:
                room_polys.append(p)
    for ins in inserts:
        (door_geoms if ins.role == "doors" else win_geoms).append(
            shapely.MultiPoint(ins.pts).convex_hull if len(ins.pts) > 2 else Point(ins.x, ins.y))

    # --- walls (per category)
    lookup = _CatLookup(wall_lines)
    segs, n_conn = close_gaps([l for l, _ in wall_lines], g["snap_tolerance"], g["gap_tolerance"])
    faces = list(polygonize(segs))
    pieces: list[tuple[Polygon, str]] = [(f, lookup.of_polygon(f)) for f in faces
                                         if f.area > 1e-5 and is_thin(f, max_t)]
    pieces += [(p, c) for p, c in wall_fills if is_thin(p, max_t)]
    n_faces = len(pieces)
    walls0 = _mp([p for p, _ in pieces])
    covered = walls0.boundary.buffer(0.004) if not walls0.is_empty else EMPTY
    leftovers = [s for s in segs if covered.is_empty or s.difference(covered).length > 0.5 * s.length]
    quads, singles, _ = pair_leftovers(leftovers, min_t, max_t, g["default_wall_thickness"], walls0)
    pieces += [(q, lookup.at(m, 0.01) or "wall") for q, m in quads]
    pieces += [(q, lookup.at(m, 0.01) or "wall") for q, m in singles]
    added, added_ends = [], []
    auto_walls = _mp([p for p, _ in pieces])
    user_walls = edits.get("add_walls") or []
    # ends shared by two drawn walls (a chain / corner) get square caps so the
    # corner is solid; free ends stay exactly where they were drawn
    shared = collections.Counter(tuple(np.round(w[k], 2)) for w in user_walls for k in ("a", "b"))
    for w in user_walls:
        t = float(w.get("thickness") or g["default_wall_thickness"])
        wa, wb = _extend_to_walls(w["a"], w["b"], auto_walls)
        u = np.array(_unit(np.asarray(wb) - np.asarray(wa)))
        if shared[tuple(np.round(w["a"], 2))] > 1:
            wa = np.asarray(wa) - u * t / 2
        if shared[tuple(np.round(w["b"], 2))] > 1:
            wb = np.asarray(wb) + u * t / 2
        added.append(LineString([wa, wb]).buffer(t / 2, cap_style="flat", join_style="mitre"))
        added_ends += [Point(wa).buffer(max(t, 0.3)), Point(wb).buffer(max(t, 0.3))]
        pieces.append((added[-1], w.get("type", "wall")))

    eps = g["snap_tolerance"]

    def clean(geom):
        geom = geom.buffer(eps, join_style="mitre").buffer(-eps, join_style="mitre")
        return _mp(_polys(geom.simplify(0.002)))

    parts = {"wall": clean(_mp([p for p, c in pieces if c == "wall"])),
             "partition": clean(_mp([p for p, c in pieces if c == "partition"]))}
    parts["partition"] = _mp(_polys(parts["partition"].difference(parts["wall"])))
    erase = _mp([_seg_rect(e["a"], e["b"], float(e.get("width") or max_t)) for e in edits.get("erase_walls") or []])
    if not erase.is_empty:
        parts = {k: _mp(_polys(v.difference(erase))) for k, v in parts.items()}
    walls = _mp(list(parts.values()))

    # --- columns
    if col_lines:
        col_polys += [p for p in polygonize(unary_union(col_lines)) if p.area > 1e-4]
    columns = _mp(col_polys)
    columns = columns.difference(walls) if not walls.is_empty else columns
    solid = _mp([walls, columns])

    # --- openings
    openings = []
    if g.get("detect_gap_openings", True):
        openings += gap_openings(walls, solid, win_geoms, door_geoms, g, arcs)
    bo = block_openings(inserts, walls, g)
    openings = _dedupe(bo + openings)
    # manual erasures / added walls override auto-detected openings there
    # (erasing a wall piece leaves two wall ends that would otherwise be
    # detected as a door with a lintel)
    manual = _mp([erase, *added])
    if not manual.is_empty:
        openings = [o for o in openings if o.poly.intersection(manual).area < 0.3 * o.poly.area]
    # hand-drawn walls never spawn automatic openings (at their ends or against
    # their faces); the user adds openings explicitly with the opening tool
    if added:
        touch = _mp([*(p.buffer(0.03) for p in added), *added_ends])
        openings = [o for o in openings if o.source != "gap" or not o.poly.intersects(touch)]
    # manual openings drawn in the editor
    for e in edits.get("add_openings") or []:
        o = _opening_from_segment(e["a"], e["b"], e.get("kind", "door"), walls, max_t)
        if o:
            openings = [x for x in openings if x.poly.intersection(o.poly).area < 0.3 * min(x.poly.area, o.poly.area)]
            openings.append(o)
    # manual kind changes / removals
    fills, kind_changes = [], []
    for e in edits.get("openings") or []:
        o = _find_opening(openings, e["at"])
        if not o:
            continue
        k = e.get("kind")
        if k:
            kind_changes.append((dataclasses.replace(o), k))    # (opening as detected, new kind)
        if k in ("none", "wall"):
            openings.remove(o)
            if k == "wall":
                fills.append(o.poly)
        elif k:
            o.kind = k
    # vitrage = very wide window, or window drawn on a vitrage layer
    vit_tree = STRtree(vit_geoms) if vit_geoms else None
    for o in openings:
        if o.kind == "window" and o.source != "manual" and (
                o.width >= float(b.get("vitrage_min_width", 99)) or (
                vit_tree is not None and len(vit_tree.query(o.poly.buffer(-0.005), predicate="intersects")))):
            o.kind = "vitrage"
        if o.kind == "door" and not o.leaves:
            o.leaves = _arc_leaves(o.poly, o.width, arcs)
    cut = _mp([o.poly for o in openings if o.source in ("block", "manual")])
    if not cut.is_empty:
        parts = {k: _mp(_polys(v.difference(cut))) for k, v in parts.items()}
    if fills:
        parts["wall"] = _mp([parts["wall"], *fills])
    walls = _mp(list(parts.values()))

    # --- insulation / cladding: keep what is attached to walls, clear openings
    if ins_lines:
        ins_segs, _ = close_gaps(ins_lines, g["snap_tolerance"], g["gap_tolerance"])
        ins_polys += [f for f in polygonize(ins_segs) if f.area > 1e-4 and is_thin(f, max_t)]
    if ins_polys and not walls.is_empty:
        near = walls.buffer(0.05)
        ins = _mp([p for p in ins_polys if p.intersects(near)])
        clear = _mp([_opening_rect(o, 0.8) for o in openings])
        ins = ins.difference(walls)
        if not clear.is_empty:
            ins = ins.difference(clear)
        ins = _mp([p for p in _polys(ins) if p.area > 0.005])
        if not ins.is_empty:
            parts["wall"] = clean(_mp([parts["wall"], ins]))
            walls = _mp(list(parts.values()))
    columns = columns.difference(walls) if not walls.is_empty else columns
    solid = _mp([walls, columns])

    # --- rooms / slab
    footprint = _footprint(solid, openings)
    labels = room_labels(texts, g.get("room_label_ignore"))
    if room_polys:
        rooms = []
        for p in room_polys:
            inside = sorted([t for t in labels if p.contains(Point(t.x, t.y))], key=lambda t: -t.height)
            rooms.append(Room(p, " ".join(inside[0].text.split())[:60] if inside else "", round(p.area, 2)))
    else:
        rooms = find_rooms(footprint, solid, openings, labels, g["min_room_area"])
    for e in edits.get("rooms") or []:
        pt = Point(e["at"])
        for r in rooms:
            if r.poly.contains(pt):
                r.name = str(e.get("name", ""))[:60]

    plan.walls, plan.wall_parts, plan.columns = walls, parts, columns
    plan.openings, plan.rooms, plan.footprint, plan.stairs = openings, rooms, footprint, stairs
    kinds = collections.Counter(o.kind for o in openings)
    plan.stats = {
        "wall_segments": len(segs), "gap_connectors": n_conn, "wall_faces": n_faces,
        "paired_strips": len(quads), "single_line_walls": len(singles),
        "wall_area_m2": round(walls.area, 2), "partition_area_m2": round(parts["partition"].area, 2),
        "columns": len(_polys(columns)), "openings": dict(kinds), "door_leaves": sum(len(o.leaves) for o in openings),
        "stairs": len(stairs), "rooms": len(rooms), "footprint_m2": round(footprint.area, 2),
        "edits": sum(len(v) for v in edits.values() if isinstance(v, list)),
    }
    plan.debug = {"segments": segs, "windows": win_geoms, "doors": door_geoms,
                  # what the manual edits did (used to write them back into the DXF)
                  "added_walls": added, "erase": erase, "kind_changes": kind_changes}
    return plan


# --------------------------------------------------------- 2D export ---
def _rings(geom, nd=3):
    out = []
    for p in _polys(geom):
        out.append([np.round(np.asarray(r.coords), nd).tolist() for r in [p.exterior, *p.interiors]])
    return out


def plan_to_json(plan: FloorPlan) -> dict:
    """Plan geometry for the 2D editor (aligned plan coordinates, meters)."""
    bounds = plan.footprint.bounds if not plan.footprint.is_empty else plan.walls.bounds
    lines = [np.round(np.asarray(s.coords), 3).tolist() for s in plan.debug.get("segments", [])]
    return {
        "bounds": [round(v, 3) for v in bounds] if bounds else None,
        "walls": _rings(plan.wall_parts.get("wall", EMPTY)),
        "partitions": _rings(plan.wall_parts.get("partition", EMPTY)),
        "columns": _rings(plan.columns),
        "footprint": _rings(plan.footprint),
        "openings": [{
            "id": o.id, "kind": o.kind, "source": o.source, "width": round(o.width, 3),
            "center": [round(o.center[0], 3), round(o.center[1], 3)],
            "poly": _rings(o.poly)[0] if _rings(o.poly) else [],
            "leaves": [[list(map(float, h)), list(map(float, t))] for h, t in o.leaves],
        } for o in plan.openings],
        "rooms": [{
            "name": r.name, "area": r.area, "poly": _rings(r.poly)[0],
            "label": [round(c, 3) for c in r.poly.representative_point().coords[0]],
        } for r in plan.rooms],
        "stairs": [_rings(st.poly)[0] for st in plan.stairs],
        "lines": lines,
    }
