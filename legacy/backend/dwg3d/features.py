"""Plan features recognised from raw linework: stairs and door swing arcs."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

STAIR_SOURCE_ROLES = (None, "walls", "stairs")


@dataclass
class Stair:
    treads: list[Polygon]            # strips between consecutive tread lines, climbing order
    direction: tuple[float, float]   # unit climb direction in plan
    going: float                     # tread depth
    width: float
    poly: Polygon = field(default=None)

    def __post_init__(self):
        if self.poly is None:
            self.poly = unary_union(self.treads).convex_hull


@dataclass
class DoorArc:
    center: tuple[float, float]      # hinge
    r: float                         # leaf width
    p0: tuple[float, float]          # arc end points
    p1: tuple[float, float]


def _unit(v):
    n = math.hypot(v[0], v[1])
    return np.array((v[0] / n, v[1] / n)) if n > 1e-12 else np.zeros(2)


def detect_stairs(shapes, g) -> tuple[list[Stair], set[int]]:
    """Runs of >= N parallel, equal-length, equally spaced lines = a flight.

    Returns the stairs and the indices of `shapes` that were consumed
    (so the treads are not mistaken for walls)."""
    tmin, tmax = g.get("stair_tread", [0.2, 0.42])
    wmin, wmax = g.get("stair_width", [0.7, 4.0])
    nmin = int(g.get("stair_min_treads", 5))
    segs, owner = [], []
    for si, s in enumerate(shapes):
        if s.role not in STAIR_SOURCE_ROLES or s.arc is not None or s.kind in ("HATCH", "SOLID"):
            continue
        p = s.pts
        for k in range(len(p) - 1):
            L = float(np.hypot(*(p[k + 1] - p[k])))
            if wmin <= L <= wmax:
                segs.append((p[k], p[k + 1]))
                owner.append(si)
    if len(segs) < nmin:
        return [], set()
    geoms = [LineString(s) for s in segs]
    tree = STRtree(geoms)
    link: dict[int, tuple[int, float]] = {}
    for i, (a, b) in enumerate(segs):
        u = _unit(b - a)
        n = np.array((-u[1], u[0]))
        L = float(np.dot(b - a, u))
        best = None
        for j in tree.query(geoms[i].buffer(tmax)):
            if j == i:
                continue
            c, d = segs[j]
            v = _unit(d - c)
            if abs(float(np.dot(u, v))) < math.cos(math.radians(2)):
                continue
            off = float(np.dot((c + d) / 2 - a, n))
            if not (tmin <= off <= tmax):
                continue
            s0, s1 = sorted((float(np.dot(c - a, u)), float(np.dot(d - a, u))))
            ov = min(L, s1) - max(0.0, s0)
            if ov < 0.85 * max(L, s1 - s0) or abs((s1 - s0) - L) > 0.15 * L:
                continue
            if best is None or off < best[1]:
                best = (j, off)
        if best:
            link[i] = best
    targets = {j for j, _ in link.values()}
    stairs, used = [], set()
    visited = set()
    for start in range(len(segs)):
        if start in targets or start not in link or start in visited:
            continue
        chain, gaps = [start], []
        cur = start
        while cur in link and link[cur][0] not in chain:
            nxt, off = link[cur]
            if gaps and abs(off - np.median(gaps)) > 0.04:
                break
            chain.append(nxt)
            gaps.append(off)
            cur = nxt
        visited.update(chain)
        if len(chain) < nmin:
            continue
        treads = []
        for k in range(len(chain) - 1):
            (a, b), (c, d) = segs[chain[k]], segs[chain[k + 1]]
            u = _unit(b - a)
            if np.dot(d - c, u) < 0:
                c, d = d, c
            q = Polygon([a, b, d, c])
            if q.is_valid and q.area > 0.01:
                treads.append(q)
        if len(treads) < nmin - 1:
            continue
        a, b = segs[chain[0]]
        u = _unit(b - a)
        n = np.array((-u[1], u[0]))
        stairs.append(Stair(treads, (float(n[0]), float(n[1])), float(np.median(gaps)),
                            float(np.hypot(*(b - a)))))
        used.update(owner[k] for k in chain)
    # a shape (polyline) is consumed only if all its segments were treads
    return stairs, {si for si in used if len(shapes[si].pts) == 2}


def detect_door_arcs(shapes, g) -> list[DoorArc]:
    rmin, rmax = g.get("door_arc_radius", [0.5, 1.5])
    out = []
    for s in shapes:
        if s.arc is None or s.role in ("ignore", "grid", "windows", "columns"):
            continue
        cx, cy, r, a0, a1 = s.arc
        sweep = (a1 - a0) % 360
        if not (75 <= sweep <= 105 and rmin <= r <= rmax):
            continue
        p0 = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
        p1 = (cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1)))
        out.append(DoorArc((cx, cy), r, p0, p1))
    return out
