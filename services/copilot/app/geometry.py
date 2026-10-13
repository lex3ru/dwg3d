"""A little plane geometry for putting objects into a room without the planning service: points inside a polygon."""
from __future__ import annotations

import math

XY = tuple[float, float]


def inside(p: XY, poly: list[XY]) -> bool:
    x, y = p
    hit = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            hit = not hit
    return hit


def centroid(poly: list[XY]) -> XY:
    a = cx = cy = 0.0
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        f = x1 * y2 - x2 * y1
        a += f
        cx += (x1 + x2) * f
        cy += (y1 + y2) * f
    if abs(a) < 1e-9:
        return (sum(x for x, _ in poly) / n, sum(y for _, y in poly) / n)
    return (cx / (3 * a), cy / (3 * a))


def spread(poly: list[XY], count: int, step: float = 1.0, inset: float = 0.5) -> list[XY]:
    """`count` points on a grid inside the polygon, the ones nearest the centre first; fewer if the room is small
    (then the rest are stacked at the centre, so nothing is lost — a human will move them)."""
    if not poly or count <= 0:
        return []
    xs, ys = [x for x, _ in poly], [y for _, y in poly]
    c = centroid(poly)
    pts: list[XY] = []
    x = min(xs) + inset
    while x <= max(xs) - inset + 1e-9:
        y = min(ys) + inset
        while y <= max(ys) - inset + 1e-9:
            if inside((x, y), poly):
                pts.append((round(x, 2), round(y, 2)))
            y += step
        x += step
    pts.sort(key=lambda p: math.hypot(p[0] - c[0], p[1] - c[1]))
    out = pts[:count]
    while len(out) < count:
        out.append((round(c[0], 2), round(c[1], 2)))
    return out
