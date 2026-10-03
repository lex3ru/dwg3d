"""Routes of people on the server, as the viewer computes them
(frontend/src/viewer/route.ts, routing.ts): for the copilot to lay out routes
and check flows.

A floor's plan becomes a walkability grid: inside the building's footprint,
away (CLEARANCE) from walls, partitions, columns, glazing and the furniture
standing on the floor; door openings are gaps in the walls, so they pass.
The way between two points of a floor is the shortest path over the grid
(8 directions, no corner cutting; scipy's Dijkstra), straightened by line of
sight. Between floors a route goes by a stair or lift found on both floors at
about the same place; the fastest connection wins.

Checks: routes of flows that must not meet (shapes.FLOW_CONFLICTS) crossing
or running side by side, and routes entering zones forbidden to their flow
(shapes.ZONE_FORBIDDEN).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import Polygon
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import planning, shapes
from .models import Build, Drawing, Floor, Layer, LayerObject
from .rooms import polygon

RES = 0.15                      # grid cell, m
CLEARANCE = 0.25                # kept from obstacles, m
MAX_CELLS = 1_500_000
WALK_SPEED = 1.3                # m/s
STAIR_S_PER_FLOOR = 15
LIFT_WAIT_S, LIFT_S_PER_FLOOR = 30, 4
SAME_SHAFT_M = 4.0              # a stair / lift on two floors: within this distance in plan
NEAR_M = 0.6                    # ways closer than this share the corridor


class RouteError(ValueError):
    """No way (the message says where)."""


@dataclass
class Grid:
    x0: float
    y0: float
    res: float
    w: int
    h: int
    free: np.ndarray            # bool, h × w

    def cell(self, p) -> tuple[int, int]:
        return int(round((p[0] - self.x0) / self.res)), int(round((p[1] - self.y0) / self.res))

    def point(self, i: int) -> list[float]:
        return [round(self.x0 + (i % self.w) * self.res, 3), round(self.y0 + (i // self.w) * self.res, 3)]


def _polys(items) -> list[Polygon]:
    return [g for rings in items or [] if (g := polygon(rings)) is not None and not g.is_empty]


def build_grid(plan: dict, extra: list[Polygon] = (), res: float = RES, clearance: float = CLEARANCE) -> Grid | None:
    if not plan or not plan.get("bounds") or not plan.get("footprint"):
        return None
    bx0, by0, bx1, by1 = plan["bounds"]
    x0, y0 = bx0 - 1, by0 - 1
    w, h = math.ceil((bx1 - bx0 + 2) / res), math.ceil((by1 - by0 + 2) / res)
    if w * h > MAX_CELLS:
        return build_grid(plan, extra, res * 1.5, clearance)
    inside = unary_union(_polys(plan["footprint"]))
    windows = [o["poly"] for o in plan.get("openings") or [] if o.get("kind") in ("window", "vitrage")]
    blocked = unary_union(_polys(plan.get("walls")) + _polys(plan.get("partitions")) + _polys(plan.get("columns"))
                          + _polys(windows) + list(extra)).buffer(clearance)
    free_area = inside.difference(blocked).difference(inside.boundary.buffer(clearance))
    shapely.prepare(free_area)
    xs, ys = np.meshgrid(x0 + np.arange(w) * res, y0 + np.arange(h) * res)
    return Grid(x0, y0, res, w, h, shapely.contains_xy(free_area, xs, ys))


def _nearest_free(g: Grid, c: tuple[int, int], max_r: int = 20) -> int | None:
    cx, cy = c
    for r in range(max_r + 1):
        best, bd = None, math.inf
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                x, y = cx + dx, cy + dy
                if 0 <= x < g.w and 0 <= y < g.h and g.free[y, x] and dx * dx + dy * dy < bd:
                    best, bd = y * g.w + x, dx * dx + dy * dy
        if best is not None:
            return best
    return None


def _line_free(g: Grid, a: int, b: int) -> bool:
    x0, y0, x1, y1 = a % g.w, a // g.w, b % g.w, b // g.w
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        if not g.free[y0, x0]:
            return False
        if x0 == x1 and y0 == y1:
            return True
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class Walker:
    """Shortest ways on one floor's grid (the graph built once)."""

    def __init__(self, g: Grid):
        self.g = g
        free = g.free
        idx = np.arange(g.w * g.h).reshape(g.h, g.w)
        rows, cols, cost = [], [], []
        for dx, dy, c in ((1, 0, 1.0), (0, 1, 1.0), (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2))):
            ys = slice(max(0, -dy), g.h - max(0, dy))
            xs = slice(0, g.w - dx)
            ys2 = slice(ys.start + dy, ys.stop + dy)
            xs2 = slice(dx, g.w)
            ok = free[ys, xs] & free[ys2, xs2]
            if dx and dy:                                   # no corner cutting
                ok &= free[ys, xs2] & free[ys2, xs]
            a, b = idx[ys, xs][ok], idx[ys2, xs2][ok]
            rows += [a, b]
            cols += [b, a]
            cost += [np.full(a.size, c), np.full(a.size, c)]
        n = g.w * g.h
        self.graph = coo_matrix((np.concatenate(cost), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()

    def path(self, a, b) -> tuple[list[list[float]], float] | None:
        g = self.g
        s, t = _nearest_free(g, g.cell(a)), _nearest_free(g, g.cell(b))
        if s is None or t is None:
            return None
        if s == t:
            pts = [list(a), list(b)]
        else:
            dist, prev = dijkstra(self.graph, indices=s, return_predecessors=True, min_only=False)
            if not math.isfinite(dist[t]):
                return None
            cells = [t]
            while cells[-1] != s:
                cells.append(int(prev[cells[-1]]))
            cells.reverse()
            keep, anchor = [cells[0]], 0                     # string pulling
            for k in range(2, len(cells)):
                if not _line_free(g, cells[anchor], cells[k]):
                    keep.append(cells[k - 1])
                    anchor = k - 1
            keep.append(cells[-1])
            pts = [g.point(i) for i in keep]
            pts[0], pts[-1] = [round(a[0], 3), round(a[1], 3)], [round(b[0], 3), round(b[1], 3)]
        return pts, sum(math.dist(pts[k - 1], pts[k]) for k in range(1, len(pts)))


# ---------------------------------------------------------------- routes ---
class Router:
    """Routes over a drawing's current build (grids built on demand, kept for the call)."""

    def __init__(self, s: Session, d: Drawing):
        self.s, self.d = s, d
        b = s.get(Build, (d.id, d.current_build)) if d.current_build else None
        res = (b.result or {}) if b else {}
        cx, cy = res.get("center") or [0, 0]
        self.floors = {f["id"]: f for f in res.get("floors") or []}
        self.order = [f["id"] for f in sorted(self.floors.values(), key=lambda f: f.get("elevation") or 0)]
        self.conns = [{"kind": p["kind"], "floor": p["floor"], "at": (p["pos"][0] + cx, -p["pos"][2] + cy)}
                      for p in res.get("pois") or [] if p.get("kind") in ("stair", "lift")]
        self._walkers: dict[str, Walker | None] = {}

    def walker(self, cand: str) -> Walker | None:
        if cand not in self._walkers:
            f = self.s.scalar(select(Floor).where(Floor.drawing_id == self.d.id, Floor.candidate == cand))
            plan = planning.load_plan(self.s, self.d.id, f) if f else None
            extra = []
            if f is not None:                                # furniture standing on visible layers blocks the way
                visible = set(self.s.scalars(select(Layer.id).where(Layer.project_id == self.d.project_id, Layer.visible)))
                extra = [planning.footprint((o.x, o.y), o.angle, *planning.item_size(o, c)[:2])
                         for o, c in planning.floor_items(self.s, f.id)
                         if o.layer_id in visible and not planning.is_high(o, c) and not planning.is_flat(c)]
            g = build_grid(plan, extra) if plan else None
            self._walkers[cand] = Walker(g) if g is not None and g.free.any() else None
        return self._walkers[cand]

    def floor_name(self, cand: str) -> str:
        return (self.floors.get(cand) or {}).get("name") or cand

    def compute(self, stops: list[dict]) -> dict:
        """{path: [{floor, pts}], length, time, floors_changed, problem?} through the stops {floor, at, label}."""
        out = {"path": [], "length": 0.0, "time": 0.0, "floors_changed": 0}

        def add(floor, pts):
            if out["path"] and out["path"][-1]["floor"] == floor:
                out["path"][-1]["pts"] += pts[1:]
            else:
                out["path"].append({"floor": floor, "pts": list(pts)})

        label = lambda st, i: st.get("label") or f"остановка {i + 1}"  # noqa: E731
        for i in range(1, len(stops)):
            a, b = stops[i - 1], stops[i]
            wa = self.walker(a["floor"])
            if a["floor"] == b["floor"]:
                p = wa.path(a["at"], b["at"]) if wa else None
                if p is None:
                    return {**out, "problem": f"Нет прохода от «{label(a, i - 1)}» до «{label(b, i)}»"}
                add(a["floor"], p[0])
                out["length"] += p[1]
                out["time"] += p[1] / WALK_SPEED
                continue
            wb = self.walker(b["floor"])
            n = abs(self.order.index(a["floor"]) - self.order.index(b["floor"])) if a["floor"] in self.order and b["floor"] in self.order else 1
            pairs = []
            for ca in (c for c in self.conns if c["floor"] == a["floor"]):
                cb = next((c for c in self.conns if c["floor"] == b["floor"] and c["kind"] == ca["kind"]
                           and math.dist(c["at"], ca["at"]) < SAME_SHAFT_M), None)
                if cb:
                    pairs.append((math.dist(a["at"], ca["at"]) + math.dist(cb["at"], b["at"]), ca, cb))
            best = None
            for _, ca, cb in sorted(pairs, key=lambda x: x[0])[:4]:
                pa = wa.path(a["at"], ca["at"]) if wa else None
                pb = wb.path(cb["at"], b["at"]) if wb else None
                if not pa or not pb:
                    continue
                vertical = LIFT_WAIT_S + LIFT_S_PER_FLOOR * n if ca["kind"] == "lift" else STAIR_S_PER_FLOOR * n
                t = (pa[1] + pb[1]) / WALK_SPEED + vertical
                if best is None or t < best[0]:
                    best = (t, pa[1] + pb[1], pa[0], pb[0])
            if best is None:
                return {**out, "problem": f"Нет лестницы или лифта, соединяющих «{self.floor_name(a['floor'])}» и "
                                          f"«{self.floor_name(b['floor'])}» на пути к «{label(b, i)}»"}
            add(a["floor"], best[2])
            add(b["floor"], best[3])
            out["length"] += best[1]
            out["time"] += best[0]
            out["floors_changed"] += n
        out["length"], out["time"] = round(out["length"], 1), round(out["time"])
        return out


# ------------------------------------------------------------------ flows ---
def _samples(pts, step: float = 0.5):
    out = [tuple(pts[0])] if pts else []
    for k in range(1, len(pts)):
        (x0, y0), (x1, y1) = pts[k - 1], pts[k]
        n = max(1, math.ceil(math.dist(pts[k - 1], pts[k]) / step))
        out += [(x0 + (x1 - x0) * j / n, y0 + (y1 - y0) * j / n) for j in range(1, n + 1)]
    return out


def check_flows(routes: list[dict], zones: list[dict]) -> list[dict]:
    """routes: {id, name, flow, path: [{floor, pts}]}; zones: {id, name, zone, floor, pts}.
    Where flows that must not meet cross or run side by side, and where routes enter
    zones forbidden to their flow (one point per pair and floor)."""
    from shapely.geometry import LineString, Point
    bad = {(x, y) for x, y in shapes.FLOW_CONFLICTS} | {(y, x) for x, y in shapes.FLOW_CONFLICTS}
    flow = lambda f: shapes.FLOWS.get(f, {}).get("name", f)  # noqa: E731
    out = []
    for i, a in enumerate(routes):
        for b in routes[i + 1:]:
            if (a["flow"], b["flow"]) not in bad:
                continue
            for sa in a["path"]:
                for sb in b["path"]:
                    if sa["floor"] != sb["floor"] or len(sb["pts"]) < 2:
                        continue
                    line = LineString(sb["pts"])
                    hit = next((p for p in _samples(sa["pts"]) if line.distance(Point(p)) < NEAR_M), None)
                    if hit:
                        out.append({"kind": "flows", "a": a["id"], "b": b["id"], "floor": sa["floor"],
                                    "at": [round(hit[0], 2), round(hit[1], 2)],
                                    "text": f"«{a['name'] or flow(a['flow'])}» ({flow(a['flow']).lower()}) и "
                                            f"«{b['name'] or flow(b['flow'])}» ({flow(b['flow']).lower()}) пересекаются"})
                        break
    for r in routes:
        for z in zones:
            if r["flow"] not in shapes.ZONE_FORBIDDEN.get(z["zone"], []) or len(z["pts"]) < 3:
                continue
            poly = Polygon(z["pts"])
            hit = next((p for sg in r["path"] if sg["floor"] == z["floor"] for p in _samples(sg["pts"])
                        if poly.contains(Point(p))), None)
            if hit:
                zname = z["name"] or shapes.ZONE_KINDS.get(z["zone"], {}).get("name", z["zone"])
                out.append({"kind": "zone", "a": r["id"], "b": z["id"], "floor": z["floor"],
                            "at": [round(hit[0], 2), round(hit[1], 2)],
                            "text": f"«{r['name'] or flow(r['flow'])}» ({flow(r['flow']).lower()}) заходит в зону «{zname}»"})
    return out


def routes_and_zones(s: Session, d: Drawing) -> tuple[list[dict], list[dict]]:
    """A drawing's computed routes {id, name, flow, path} and zones {id, name, zone, floor, pts}
    (floors by the current build's ids), as check_flows takes them."""
    from . import viewdata
    floors = viewdata._floors(s, d.id)
    routes, zones = [], []
    for o in s.scalars(select(LayerObject).where(LayerObject.drawing_id == d.id, LayerObject.geom.in_(("route", "polygon")))):
        j = viewdata.object_json(o, floors)
        pr = j.get("props") or {}
        if o.geom == "route" and pr.get("path"):
            routes.append({"id": o.id, "name": pr.get("name") or "", "flow": pr.get("flow") or "",
                           "path": [sg for sg in pr["path"] if sg.get("floor")]})
        elif o.geom == "polygon" and pr.get("zone") and j["floor"]:
            zones.append({"id": o.id, "name": pr.get("name") or "", "zone": pr["zone"], "floor": j["floor"],
                          "pts": j.get("points") or []})
    return routes, zones


def flows_of(s: Session, d: Drawing) -> list[dict]:
    """The flow conflicts of a drawing's routes and zones."""
    return check_flows(*routes_and_zones(s, d))
