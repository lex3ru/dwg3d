"""Plane geometry helpers: Bezier curves -> lines / circular arcs."""
from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]

EPS = 1e-6


@dataclass
class Seg:
    """A straight (bulge == 0) or circular segment from p0 to p1.

    bulge follows the DXF convention: tan(sweep / 4), positive = counter-clockwise.
    center / radius are set for arcs only.
    """

    p0: Point
    p1: Point
    bulge: float = 0.0
    center: Point | None = None
    radius: float = 0.0

    @property
    def sweep(self) -> float:
        return 4.0 * math.atan(self.bulge)


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def bezier_point(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def flatten_bezier(p0: Point, p1: Point, p2: Point, p3: Point, tol: float) -> list[Point]:
    """Polyline approximation of a cubic Bezier, points p0..p3 inclusive."""
    chord = dist(p0, p1) + dist(p1, p2) + dist(p2, p3)
    n = max(2, min(200, int(math.sqrt(chord / max(tol, 1e-9)) * 0.6) + 1))
    return [bezier_point(p0, p1, p2, p3, i / n) for i in range(n + 1)]


def _point_line_dist(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < EPS:
        return dist(p, a)
    return abs(dx * (a[1] - p[1]) - dy * (a[0] - p[0])) / length


def circumcenter(a: Point, b: Point, c: Point) -> Point | None:
    d = 2.0 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    ux = (a2 * (b[1] - c[1]) + b2 * (c[1] - a[1]) + c2 * (a[1] - b[1])) / d
    uy = (a2 * (c[0] - b[0]) + b2 * (a[0] - c[0]) + c2 * (b[0] - a[0])) / d
    return (ux, uy)


def bezier_to_seg(p0: Point, p1: Point, p2: Point, p3: Point, tol: float) -> Seg | None:
    """Replace a cubic Bezier by a line or a circular arc if the error is below tol.

    Returns None when the curve is neither (caller keeps it as a spline).
    """
    if dist(p0, p3) < EPS:
        return None  # closed loop: needs more than one arc
    if _point_line_dist(p1, p0, p3) <= tol and _point_line_dist(p2, p0, p3) <= tol:
        return Seg(p0, p3)
    mid = bezier_point(p0, p1, p2, p3, 0.5)
    c = circumcenter(p0, mid, p3)
    if c is None:
        return None
    r = dist(c, p0)
    tol_r = max(tol, 1e-3 * r)
    for t in (0.25, 0.75):
        if abs(dist(c, bezier_point(p0, p1, p2, p3, t)) - r) > tol_r:
            return None
    two_pi = 2.0 * math.pi
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    am = math.atan2(mid[1] - c[1], mid[0] - c[0])
    a3 = math.atan2(p3[1] - c[1], p3[0] - c[0])
    if (am - a0) % two_pi < (a3 - a0) % two_pi:
        sweep = (a3 - a0) % two_pi
    else:
        sweep = -((a0 - a3) % two_pi)
    if abs(sweep) >= two_pi - 1e-9 or abs(sweep) < 1e-9:
        return None
    return Seg(p0, p3, math.tan(sweep / 4.0), c, r)


def arc_angles(seg: Seg) -> tuple[float, float]:
    """(start, end) in degrees, counter-clockwise, as the DXF ARC entity wants."""
    assert seg.center is not None
    a0 = math.degrees(math.atan2(seg.p0[1] - seg.center[1], seg.p0[0] - seg.center[0]))
    a1 = math.degrees(math.atan2(seg.p1[1] - seg.center[1], seg.p1[0] - seg.center[0]))
    return (a0, a1) if seg.bulge > 0 else (a1, a0)


def is_full_circle(segs: list[Seg], tol: float) -> tuple[Point, float] | None:
    """If the closed chain of arcs is one circle, return (center, radius)."""
    if len(segs) < 2 or any(s.center is None for s in segs):
        return None
    c0, r0 = segs[0].center, segs[0].radius
    assert c0 is not None
    for s in segs:
        assert s.center is not None
        if dist(s.center, c0) > tol or abs(s.radius - r0) > tol:
            return None
    if abs(sum(abs(s.sweep) for s in segs) - 2.0 * math.pi) > 1e-2:
        return None
    return c0, r0


def reverse_seg(s: Seg) -> Seg:
    return Seg(s.p1, s.p0, -s.bulge, s.center, s.radius)


def join_chains(chains: list[list[Seg]], tol: float) -> list[tuple[list[Seg], bool]]:
    """Merge open chains that meet end to end into longer ones.

    Chains are joined only at points where exactly two chain ends meet, so T and X
    junctions stay separate. Returns (chain, closed) pairs.
    """
    cell = max(tol, 1e-6)
    grid: dict[tuple[int, int], list[tuple[int, int]]] = {}  # cell -> [(chain id, end 0/1)]

    def key(p: Point) -> tuple[int, int]:
        return (round(p[0] / cell), round(p[1] / cell))

    def end_pt(c: list[Seg], end: int) -> Point:
        return c[0].p0 if end == 0 else c[-1].p1

    for i, c in enumerate(chains):
        for end in (0, 1):
            grid.setdefault(key(end_pt(c, end)), []).append((i, end))

    def near(p: Point) -> list[tuple[int, int]]:
        kx, ky = key(p)
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i, end in grid.get((kx + dx, ky + dy), ()):
                    if dist(end_pt(chains[i], end), p) <= tol:
                        out.append((i, end))
        return out

    used = [False] * len(chains)
    result: list[tuple[list[Seg], bool]] = []

    def extend(cur: list[Seg], at_tail: bool) -> None:
        while True:
            p = cur[-1].p1 if at_tail else cur[0].p0
            hits = near(p)
            if len(hits) != 2:
                return
            other = [h for h in hits if not used[h[0]]]
            if len(other) != 1:
                return
            j, end = other[0]
            nxt = chains[j]
            used[j] = True
            if at_tail:
                cur.extend(nxt if end == 0 else [reverse_seg(s) for s in reversed(nxt)])
            else:
                prev = nxt if end == 1 else [reverse_seg(s) for s in reversed(nxt)]
                cur[:0] = prev

    for i, c in enumerate(chains):
        if used[i]:
            continue
        used[i] = True
        cur = list(c)
        extend(cur, True)
        if dist(cur[0].p0, cur[-1].p1) <= tol and len(cur) > 1:
            result.append((cur, True))
            continue
        extend(cur, False)
        result.append((cur, dist(cur[0].p0, cur[-1].p1) <= tol and len(cur) > 1))
    return result
