"""A built drawing turned into a drawn plan (app/sketch.py), to go on editing
it in the 2D editor.

Walls come as outlines (plans/floor_<id>.json of the build); a drawn plan
needs their centre lines and thicknesses. The openings are filled in first so
a wall runs through its doors; then every two faces of the wall outline that
run opposite each other at a wall's thickness, with the wall between them,
make a strip — its middle line is the wall, the distance its thickness.
Strips on one line are joined, their ends are carried on to meet the walls
they stop short of (the corners and the junctions), and where the lines cross
they are cut, as the editor does.

Openings go into the wall nearest their middle, with their kind, width, and
the side and hinge of a door's leaf; rooms keep their names, columns and
stairs their places. Each floor remembers the sheet of the drawing it came
from (`source`), so the plan's next build continues the floors and rooms the
building already has.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.strtree import STRtree

MIN_T, MAX_T = 0.04, 0.9          # what may be a wall's thickness
PARALLEL = 0.985                  # cos of faces taken as running opposite ways
MIN_OVERLAP = 0.03
STUB = 0.05                       # loose ends shorter than this are leftovers of the outline
PARTITION_T = 0.18                # thinner walls are partitions
RISER = 0.17                      # frontend/src/plan/elements.ts
REACH = 0.5                       # how far past a wall's end its corner may be
INSIDE = 0.9                      # a strip this much in the wall outline is a wall


def _polys(g) -> list[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [q for x in getattr(g, "geoms", []) for q in _polys(x)]


def _poly(rings) -> Polygon | None:
    if not rings or len(rings[0]) < 4:
        return None
    p = Polygon(rings[0], [r for r in rings[1:] if len(r) >= 4])
    return p if p.is_valid else max(_polys(p.buffer(0)), key=lambda q: q.area, default=None)


def _unit(v):
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n) if n > 1e-12 else (0.0, 0.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _along(a, d, k):
    return (a[0] + d[0] * k, a[1] + d[1] * k)


# ------------------------------------------------------------------ walls ---
def strips(mass) -> list[tuple[tuple, tuple, float]]:
    """The middle lines between the wall outline's opposite faces: (a, b, thickness)."""
    edges = []
    for p in _polys(mass):
        p = orient(p.simplify(0.003), 1.0)                 # the wall on the left of every face
        for ring in [p.exterior, *p.interiors]:
            cs = list(ring.coords)
            edges += [(a, b) for a, b in zip(cs, cs[1:], strict=False) if math.dist(a, b) > MIN_OVERLAP]
    if not edges:
        return []
    lines = [LineString(e) for e in edges]
    tree = STRtree(lines)
    near = mass.buffer(0.005)
    out = []
    for i, (a, b) in enumerate(edges):
        d = _unit(_sub(b, a))
        n = (-d[1], d[0])                                   # into the wall
        length = math.dist(a, b)
        for j in tree.query(lines[i].buffer(MAX_T)):
            if j <= i:
                continue
            c, e = edges[j]
            if _dot(d, _unit(_sub(e, c))) > -PARALLEL:
                continue
            mid = ((c[0] + e[0]) / 2, (c[1] + e[1]) / 2)
            t = _dot(_sub(mid, a), n)
            if not MIN_T <= t <= MAX_T:
                continue
            s0, s1 = sorted((_dot(_sub(c, a), d), _dot(_sub(e, a), d)))
            s0, s1 = max(s0, 0.0), min(s1, length)
            if s1 - s0 < MIN_OVERLAP:
                continue
            p0, p1 = _along(a, d, s0), _along(a, d, s1)
            band = Polygon([p0, p1, (p1[0] + n[0] * t, p1[1] + n[1] * t), (p0[0] + n[0] * t, p0[1] + n[1] * t)])
            if band.intersection(near).area < INSIDE * band.area:
                continue                                    # an empty space between two walls
            h = (n[0] * t / 2, n[1] * t / 2)
            out.append(((p0[0] + h[0], p0[1] + h[1]), (p1[0] + h[0], p1[1] + h[1]), t))
    return out


def join(segments, mass) -> list[tuple[tuple, tuple, float]]:
    """Strips on one line and of one thickness joined where they overlap, touch, or the wall runs on between them."""
    groups: list[dict] = []
    for a, b, t in segments:
        d = _unit(_sub(b, a))
        if d[0] < -1e-9 or (abs(d[0]) < 1e-9 and d[1] < 0):
            d = (-d[0], -d[1])
        for g in groups:
            gd, off = g["d"], _sub(a, g["p"])
            if (abs(gd[0] * d[1] - gd[1] * d[0]) < 0.02 and abs(gd[0] * off[1] - gd[1] * off[0]) < 0.02
                    and abs(g["t"] - t) < 0.03):
                break
        else:
            g = {"d": d, "p": a, "t": t, "spans": []}
            groups.append(g)
        k0, k1 = sorted((_dot(_sub(a, g["p"]), g["d"]), _dot(_sub(b, g["p"]), g["d"])))
        g["spans"].append((k0, k1, t))
    near = mass.buffer(0.01)
    out = []
    for g in groups:
        d, p = g["d"], g["p"]
        spans = sorted(g["spans"])
        cur = [spans[0][0], spans[0][1], [spans[0]]]
        runs = []
        for s in spans[1:]:
            gap = LineString([_along(p, d, cur[1]), _along(p, d, s[0])]) if s[0] > cur[1] else None
            if gap is None or (gap.length < MAX_T and near.contains(gap)):
                cur[1] = max(cur[1], s[1])
                cur[2].append(s)
            else:
                runs.append(cur)
                cur = [s[0], s[1], [s]]
        runs.append(cur)
        for k0, k1, parts in runs:
            weight = sum(s1 - s0 for s0, s1, _ in parts) or 1.0
            t = sum((s1 - s0) * tt for s0, s1, tt in parts) / weight
            if k1 - k0 < t:
                continue                                    # a pier or a thickening at a corner, not a wall
            out.append((_along(p, d, k0), _along(p, d, k1), round(t / 0.005) * 0.005))
    return out


def _meet(p, d, a, b):
    """Where the ray p + u·d crosses the line through a, b: (u, its place on a→b in meters), or None."""
    e = _sub(b, a)
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9 * math.hypot(*e):
        return None
    w = _sub(a, p)
    u = (w[0] * e[1] - w[1] * e[0]) / den
    s = (w[0] * d[1] - w[1] * d[0]) / den
    return u, s * math.hypot(*e)


def extend(segments, mass) -> list[tuple[tuple, tuple, float]]:
    """Each end carried on, through the wall, to the nearest wall it stops short of."""
    near = mass.buffer(0.02)
    lines = [LineString(s[:2]) for s in segments]
    tree = STRtree(lines)
    out = [list(s) for s in segments]
    for i, s in enumerate(segments):
        for end in (0, 1):
            p, q = (s[0], s[1]) if end == 0 else (s[1], s[0])
            d = _unit(_sub(p, q))                               # out of the wall
            best = None
            for j in tree.query(Point(p).buffer(MAX_T + REACH)):
                o = segments[j]
                m = None if j == i else _meet(p, d, o[0], o[1])
                if m is None:
                    continue
                u, at = m
                reach = max(s[2], o[2]) + REACH                 # through a corner, thickened or not
                length = math.dist(o[0], o[1])
                if not -0.01 <= u <= reach or not -(s[2] / 2 + REACH) <= at <= length + s[2] / 2 + REACH:
                    continue
                if best is None or u < best:
                    to = (p[0] + d[0] * u, p[1] + d[1] * u)
                    if u <= 0.01 or near.contains(LineString([p, to])):
                        best = u
            if best is not None and best > 0:
                out[i][end] = (p[0] + d[0] * best, p[1] + d[1] * best)
    return [tuple(s) for s in out]


def bridge(segments, mass) -> list[tuple[tuple, tuple, float, int]]:
    """Ends that met no wall joined, through the wall, to the nearest end of another: an arc drawn by chords,
    a wall going on past a column a little aside. Each bridge with the segment it comes from."""
    near = mass.buffer(0.02)
    lines = [LineString(s[:2]) for s in segments]
    tree = STRtree(lines)
    out, done = [], set()
    for i, s in enumerate(segments):
        for end in (0, 1):
            p = Point(s[end])
            around = [j for j in tree.query(p.buffer(MAX_T + REACH)) if j != i]
            if any(lines[j].distance(p) < 0.002 for j in around):
                continue
            best = None
            for j in around:
                for e in (0, 1):
                    q = segments[j][e]
                    dist = math.dist(s[end], q)
                    if 0.002 < dist <= s[2] + segments[j][2] + 0.3 and (best is None or dist < best[0]):
                        if near.contains(LineString([s[end], q])):
                            best = (dist, j, q)
            if best is not None and (best[1], i) not in done:
                done.add((i, best[1]))
                out.append((s[end], best[2], min(s[2], segments[best[1]][2]), i))
    return out


def graph(segments, kinds) -> tuple[dict, dict]:
    """Nodes and walls (frontend/src/plan/model.ts) of the segments cut where they cross."""
    lines = [LineString([a, b]) for a, b, _ in segments]
    tree = STRtree(lines)
    pieces = [g for g in _lines(unary_union(lines)) if g.length > 1e-6]
    nodes: dict[str, tuple] = {}
    index: dict[tuple, str] = {}

    def node(pt) -> str:
        key = (round(pt[0] / 0.002), round(pt[1] / 0.002))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                k = index.get((key[0] + dx, key[1] + dy))
                if k is not None and math.dist(nodes[k], pt) < 0.003:
                    return k
        k = f"n{len(nodes) + 1}"
        nodes[k] = [round(pt[0], 4), round(pt[1], 4)]
        index[key] = k
        return k

    walls: dict[str, dict] = {}
    for pc in pieces:
        a, b = pc.coords[0], pc.coords[-1]
        mid = pc.interpolate(0.5, normalized=True)
        src = min(tree.query(mid.buffer(1e-4)), key=lambda j: lines[j].distance(mid), default=None)
        if src is None:
            continue
        na, nb = node(a), node(b)
        if na == nb:
            continue
        walls[f"w{len(walls) + 1}"] = {"a": na, "b": nb, "thickness": segments[src][2], "height": None,
                                       "kind": kinds[src]}
    _prune(nodes, walls)
    return nodes, walls


def _lines(g):
    if g.is_empty:
        return []
    if isinstance(g, LineString):
        return [g]
    return [q for x in getattr(g, "geoms", []) for q in _lines(x)]


def _prune(nodes: dict, walls: dict) -> None:
    """Short loose ends taken away, then walls in line through a node of two joined, as the editor does."""
    while True:
        deg: dict[str, int] = {}
        for w in walls.values():
            deg[w["a"]] = deg.get(w["a"], 0) + 1
            deg[w["b"]] = deg.get(w["b"], 0) + 1
        loose = [k for k, w in walls.items()
                 if (deg[w["a"]] == 1 or deg[w["b"]] == 1) and deg[w["a"]] + deg[w["b"]] > 2
                 and math.dist(nodes[w["a"]], nodes[w["b"]]) < STUB]
        if not loose:
            break
        for k in loose:
            walls.pop(k, None)
    at: dict[str, list[str]] = {}
    for k, w in walls.items():
        at.setdefault(w["a"], []).append(k)
        at.setdefault(w["b"], []).append(k)
    for n, ks in at.items():
        if len(ks) != 2 or ks[0] not in walls or ks[1] not in walls:
            continue
        w1, w2 = walls[ks[0]], walls[ks[1]]
        if w1["kind"] != w2["kind"] or abs(w1["thickness"] - w2["thickness"]) > 1e-6:
            continue
        o1 = w1["b"] if w1["a"] == n else w1["a"]
        o2 = w2["b"] if w2["a"] == n else w2["a"]
        if o1 == o2:
            continue
        d1, d2 = _unit(_sub(nodes[n], nodes[o1])), _unit(_sub(nodes[o2], nodes[n]))
        if _dot(d1, d2) < 0.9998:
            continue
        w1.update(a=o1, b=o2)
        del walls[ks[1]]
        for m in (o2,):
            at[m] = [ks[0] if x == ks[1] else x for x in at.get(m, [])]
    used = {w["a"] for w in walls.values()} | {w["b"] for w in walls.values()}
    for k in [k for k in nodes if k not in used]:
        del nodes[k]


def _post(p: Polygon) -> bool:
    """A piece of the wall outline that is a pillar rather than a wall: small, about as wide as deep, square-cut."""
    _, _, a, b = _box(p)
    return 0.15 <= min(a, b) and max(a, b) <= 1.2 and max(a, b) < 2 * min(a, b) and p.area > 0.8 * a * b


def _column(p: Polygon) -> dict:
    at, ang, a, b = _box(p)
    return {"at": at, "shape": "rect", "width": round(max(b, 0.05), 3), "depth": round(max(a, 0.05), 3),
            "angle": round(ang, 2)}


def walls_of(plan: dict) -> tuple[dict, dict, list[dict]]:
    """The nodes and walls of a built floor's plan, and the pillars in its wall outline."""
    holes = [p for p in (_poly(o["poly"]) for o in plan.get("openings") or []) if p is not None]
    sets, posts = [], []
    for key, kind in (("walls", "bearing"), ("partitions", "partition")):
        parts = [p for p in (_poly(r) for r in plan.get(key) or []) if p is not None]
        posts += [p for p in parts if not p.buffer(0.01).intersects(unary_union(holes)) and _post(p)]
        parts = [p for p in parts if not any(p is q for q in posts)]
        if parts:
            sets.append((unary_union(parts), kind))
    if not sets:
        return {}, {}, [_column(p) for p in posts]
    everything = unary_union([m for m, _ in sets] + holes)
    found, kinds = [], []
    for mass, kind in sets:
        # an opening fills the wall it is in, so the wall runs through it
        filled = unary_union([mass, *[h.buffer(0.002) for h in holes if h.buffer(0.01).intersects(mass)]])
        for a, b, t in join(strips(filled), filled):
            if math.dist(a, b) < MIN_OVERLAP:
                continue
            found.append((a, b, t))
            kinds.append("partition" if kind == "partition" or t < PARTITION_T else "bearing")
    segs = extend(found, everything)
    for a, b, t, i in bridge(segs, everything):
        segs.append((a, b, t))
        kinds.append(kinds[i])
    nodes, walls = graph(segs, kinds)
    # what of the outline the walls do not cover — a thickened corner, a pillar in a wall — stays as a column
    body = unary_union([LineString([nodes[w["a"]], nodes[w["b"]]]).buffer(w["thickness"] / 2, cap_style="square")
                        for w in walls.values()] + holes).buffer(0.01)
    rest = [q for q in _polys(unary_union([m for m, _ in sets]).difference(body)) if q.area > 0.05 and _post(q)]
    return nodes, walls, [_column(p) for p in posts + rest]


# --------------------------------------------------------------- openings ---
def openings_of(plan: dict, nodes: dict, walls: dict, cfg: dict, height: float) -> tuple[dict, int]:
    """The openings of the plan in its walls, and how many found no wall to go into."""
    b = cfg.get("building", {})
    door_h = float(b.get("door_height", 2.1))
    sill, head = float(b.get("window_sill", 0.9)), float(b.get("window_head", 2.4))
    out, lost = {}, 0
    for o in plan.get("openings") or []:
        kind = o.get("kind") if o.get("kind") in ("door", "window", "vitrage", "passage") else "passage"
        c = Point(o["center"])
        best = None
        for wid, w in walls.items():
            a, bb = nodes[w["a"]], nodes[w["b"]]
            dist = LineString([a, bb]).distance(c)
            if dist <= w["thickness"] / 2 + 0.1 and (best is None or dist < best[0]):
                best = (dist, wid)
        if best is None:
            lost += 1
            continue
        w = walls[best[1]]
        a, bb = nodes[w["a"]], nodes[w["b"]]
        d = _unit(_sub(bb, a))
        length = math.dist(a, bb)
        width = min(max(float(o["width"]), 0.1), length)
        at = min(max(_dot(_sub(o["center"], a), d), width / 2), length - width / 2)
        hinge, side = "a", "left"
        if o.get("leaves"):
            h, tip = o["leaves"][0]
            hinge = "a" if _dot(_sub(h, a), d) < at else "b"
            side = "left" if _dot(_sub(tip, h), (-d[1], d[0])) >= 0 else "right"
        if kind == "window":
            hs = {"height": round(head - sill, 3), "sill": sill}
        elif kind == "vitrage":
            hs = {"height": round(max(0.5, height - float(b.get("vitrage_head", 0.15))), 3), "sill": 0.0}
        else:
            hs = {"height": door_h, "sill": 0.0}
        out[f"o{len(out) + 1}"] = {"wall": best[1], "kind": kind, "at": round(at, 4), "width": round(width, 3),
                                   **hs, "hinge": hinge, "side": side}
    return out, lost


# ------------------------------------------------------ rooms and elements ---
def rooms_of(plan: dict) -> dict:
    out = {}
    for r in plan.get("rooms") or []:
        name, number = (r.get("name") or "").strip(), str(r.get("number") or "").strip()
        if not name and not number:
            continue
        p = _poly(r["poly"])
        at = r.get("label")
        if p is not None and (not at or not p.contains(Point(at))):
            at = p.representative_point().coords[0]
        if not at:
            continue
        out[f"r{len(out) + 1}"] = {"at": [round(at[0], 3), round(at[1], 3)], "name": name[:200], "number": number[:40],
                                   "type": None}
    return out


def _box(p: Polygon) -> tuple[tuple, float, float, float]:
    """The middle, the angle (degrees) and the two sides of the smallest box around p, the first along the angle."""
    r = p.minimum_rotated_rectangle
    cs = list(r.exterior.coords) if isinstance(r, Polygon) else [p.centroid.coords[0]] * 4
    e1, e2 = _sub(cs[1], cs[0]), _sub(cs[2], cs[1])
    c = r.centroid.coords[0]
    return [round(c[0], 4), round(c[1], 4)], math.degrees(math.atan2(e1[1], e1[0])), math.hypot(*e1), math.hypot(*e2)


def columns_of(plan: dict, pillars: list[dict]) -> dict:
    out = {f"c{i + 1}": c for i, c in enumerate(pillars)}
    for rings in plan.get("columns") or []:
        p = _poly(rings)
        if p is None or p.area < 1e-4:
            continue
        at, ang, a, b = _box(p)
        round_ = abs(a - b) < 0.1 * max(a, b) and abs(p.area / (a * b) - math.pi / 4) < 0.06
        if round_:
            out[f"c{len(out) + 1}"] = {"at": at, "shape": "round", "width": round((a + b) / 2, 3),
                                       "depth": round((a + b) / 2, 3), "angle": 0.0}
        else:
            out[f"c{len(out) + 1}"] = _column(p)
    return out


def stairs_of(plan: dict, height: float) -> dict:
    out = {}
    for ring in plan.get("stairs") or []:
        p = _poly(ring)
        if p is None or p.area < 0.05:
            continue
        at, ang, a, b = _box(p)
        if b > a:                                           # climbing along the longer side
            a, b, ang = b, a, ang + 90
        out[f"s{len(out) + 1}"] = {"at": at, "width": round(max(b, 0.3), 3), "length": round(max(a, 0.5), 3),
                                   "angle": round(ang % 360, 2), "steps": max(2, math.ceil(height / RISER - 1e-9))}
    return out


# ------------------------------------------------------------------ floors ---
def floor_of(meta: dict, plan: dict, cfg: dict) -> tuple[dict, list[str]]:
    """A drawn floor (app/sketch.py) of a built one: its meta in the build's result and its plan."""
    height = float(meta.get("height") or 3.0)
    nodes, walls, pillars = walls_of(plan)
    openings, lost = openings_of(plan, nodes, walls, cfg, height)
    name = meta.get("name") or f"Этаж {meta.get('level', '')}".strip()
    floor = {
        "id": str(meta["id"])[:64], "name": name[:200], "level": int(meta.get("level") or 1),
        "elevation": float(meta.get("elevation") or 0.0), "height": max(height, 0.5),
        "nodes": nodes, "walls": walls, "openings": openings, "rooms": rooms_of(plan),
        "columns": columns_of(plan, pillars), "stairs": stairs_of(plan, height), "underlay": None,
        "source": {"space": str(meta.get("space") or "Model"), "owner": meta.get("owner"),
                   "bbox": [float(v) for v in meta["bbox"]],
                   "offset": [float(v) for v in (meta.get("offset") or (0.0, 0.0))]},
    }
    notes = []
    if lost:
        notes.append(f"{name}: {lost} проём(ов) не попали ни в одну стену")
    if not walls:
        notes.append(f"{name}: стены не распознаны")
    return floor, notes


def sketch_of(result: dict, plans: dict[str, dict], cfg: dict) -> tuple[dict, list[str]]:
    """The drawn plan of a build: its result (metadata.json) and its plans by floor id."""
    floors, notes = [], []
    for meta in result.get("floors") or []:
        plan = plans.get(meta["id"])
        if plan is None or not meta.get("bbox"):
            continue
        f, n = floor_of(meta, plan, cfg)
        floors.append(f)
        notes += n
    floors.sort(key=lambda f: (f["level"], f["elevation"]))
    return {"version": 1, "floors": floors}, notes
