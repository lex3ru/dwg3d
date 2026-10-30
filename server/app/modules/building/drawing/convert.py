"""Часть чертежа → план этажа (5.1.3 п. 2–3)."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from shapely import STRtree, unary_union
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize

from app.modules.building import geometry
from app.modules.building.drawing import captions, glyphs, walls
from app.modules.building.drawing.layers import NOT_NUMBERS, labels_layer, role, text_kind
from app.modules.building.drawing.read import Drawing, Seg
from app.modules.building.plan import Column, Opening, Plan, RoomLabel, Wall

NODE = 5.0  # мм: точки ближе — один узел
LONG = 1000.0  # мм: линия не короче — линия здания, а не штрих, значок или буква
WALL_SHARE = 0.1  # длинных линий на слоях стен меньше этой доли от прочих — стены и на «0»
# мм: линия прочего слоя не дальше от обрыва стены — кандидат в окна (R-059); проёма шире не
# бывает (walls.join, _bridge), а окно в широком проёме бывает нарисовано кусками
END = walls.WIDE_MAX
MAX_WINDOW_LINES = 20_000  # больше кандидатов — только самые длинные
# этапы перевода части — ход виден и внутри части (R-059)
STAGES = ("стены", "проёмы", "окна и витражи", "узлы и проверка", "помещения")
HEIGHTS = {
    "door": (2100.0, 0.0),
    "window": (1500.0, 800.0),
    "passage": (2100.0, 0.0),
    "glazing": (2700.0, 0.0),
}


def _uid(prefix: str, taken: set[str]) -> str:
    i = len(taken) + 1
    while f"{prefix}{i}" in taken:
        i += 1
    taken.add(f"{prefix}{i}")
    return f"{prefix}{i}"


@dataclass
class Result:
    plan: Plan
    notes: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _inside(bbox: tuple[float, float, float, float], p: tuple[float, float]) -> bool:
    return bbox[0] - 1 <= p[0] <= bbox[2] + 1 and bbox[1] - 1 <= p[1] <= bbox[3] + 1


def _has_walls(segs: list[Seg], roles: dict[str, str]) -> bool:
    """Стены части — на слоях стен, а не на «0» и прочих: длинных линий на слоях стен хотя бы
    WALL_SHARE от длинных линий прочих слоёв. Слой стен с одним обрывком или значками — не
    повод терять здание, начерченное на «0» (R-058). Штриховки и текст линиями — короткие и
    не в счёт."""
    length = {"wall": 0.0, "other": 0.0}
    for s in segs:
        r = roles[s.layer]
        d = math.dist(s.a, s.b)
        if d >= LONG:
            if r in ("wall", "partition"):
                length["wall"] += d
            elif r == "other":
                length["other"] += d
    return length["wall"] > 0 and length["wall"] >= WALL_SHARE * length["other"]


def _near_ends(segs: list[Seg], strips: list[walls.Strip], notes: list[str]) -> list[Seg]:
    """Линии прочих слоёв у обрывов стен — там, где бывает окно (R-059): полоса шириной со
    стену на END за каждым концом полосы стены. Фигура, задевшая полосу, берётся целиком.
    Остальное (штриховки, мебель, текст линиями — сотни тысяч линий) в окна не годится."""
    if not segs or not strips:
        return []
    bands = []
    for s in strips:
        d = walls._unit(walls._sub(s.b, s.a))
        n = (-d[1], d[0])
        h = s.t / 2 + 100
        for p, out in ((s.a, (-d[0], -d[1])), (s.b, d)):
            p0, p1 = walls._along(p, out, -50), walls._along(p, out, END)
            bands.append(Polygon([walls._along(p0, n, h), walls._along(p1, n, h),
                                  walls._along(p1, n, -h), walls._along(p0, n, -h)]))
    _, hit = STRtree(walls.lines_of(segs)).query(bands, predicate="intersects")
    shapes = {segs[int(i)].shape for i in hit}
    out = [s for s in segs if s.shape in shapes]
    if len(out) > MAX_WINDOW_LINES:
        out = sorted(out, key=lambda s: -math.dist(s.a, s.b))[:MAX_WINDOW_LINES]
        notes.append(f"Окна на слоях без роли искались по {MAX_WINDOW_LINES} самым длинным "
                     "линиям у обрывов стен: их там слишком много")
    return out


def convert(drawing: Drawing, bbox: tuple[float, float, float, float],
            step: Callable[[int, str], None] | None = None) -> Result:
    """step(i, этап) — перед каждым этапом из STAGES, чтобы ход был виден внутри части."""

    def stage(i: int) -> None:
        if step is not None:
            step(i, STAGES[i])

    stage(0)
    segs = [s for s in drawing.segs if _inside(bbox, s.a) and _inside(bbox, s.b)]
    roles = {s.layer: role(s.layer) for s in segs}
    has_walls = _has_walls(segs, roles)
    wall_roles = {"wall", "partition"} if has_walls else {"wall", "partition", "other"}
    wall_segs = [s for s in segs if roles[s.layer] in wall_roles]
    column_segs = [s for s in segs if roles[s.layer] == "column"]
    arcs = [a for a in drawing.arcs if _inside(bbox, a.center) and role(a.layer) != "ignore"]
    fills = [
        f
        for f in drawing.fills
        if role(f.layer) in ("wall", "partition", "fill")
        and all(_inside(bbox, p) for p in f.ring[:3])
    ]
    column_fills = [
        f
        for f in drawing.fills
        if role(f.layer) == "column" and all(_inside(bbox, p) for p in f.ring[:3])
    ]

    body, columns, noise = walls.mass(wall_segs, fills)
    columns += _column_shapes(column_segs, column_fills)
    partition_lines = [LineString([s.a, s.b]) for s in wall_segs if roles[s.layer] == "partition"]
    partition_tree = STRtree(partition_lines) if partition_lines else None

    def kind_of(p: Point, t: float) -> str:
        if partition_tree is not None and any(
            partition_lines[int(j)].distance(p) <= t / 2 + 20
            for j in partition_tree.query(p.buffer(t / 2 + 20))
        ):
            return "partition"
        return "bearing" if t >= 180 else "partition"

    strips = walls.strips(body, kind_of)
    stage(1)
    notes: list[str] = []
    # окна бывают и на слое окон, и блоками на слое «0»: в проёме стены годятся оба, но из
    # прочих слоёв — только линии у обрывов стен
    window_segs = [s for s in segs if roles[s.layer] == "window"]
    if has_walls:
        window_segs += _near_ends([s for s in segs if roles[s.layer] == "other"], strips, notes)
    window_lines = [LineString([s.a, s.b]) for s in window_segs]
    joined, gaps = walls.join(strips, body, window_lines, arcs)
    stage(2)
    # окна, витражи между простенками: полосы из линий окон, не попавшие в проёмы стен
    window_body, _, _ = walls.mass(window_segs, [])
    reach = body.buffer(150)
    hug = body.buffer(250)
    window_strips = [
        w
        for w in walls.join(walls.strips(window_body, lambda p, t: "window"), window_body, [], [])[
            0
        ]
        if not _in_gap(w, gaps)
        and math.dist(w.a, w.b) >= 400
        # окно стоит между простенками: оба конца у стен
        and reach.contains(Point(w.a))
        and reach.contains(Point(w.b))
        # а не вдоль стены (облицовка, наружная линия фасада)
        and LineString([w.a, w.b]).intersection(hug).length < 0.5 * math.dist(w.a, w.b)
    ]
    both = unary_union([body, window_body])
    extended = walls.extend(joined + window_strips, both)
    stage(3)
    plan, glazed = _graph(extended)
    _openings(plan, gaps)
    _glazing(plan, glazed)
    _bridge(plan, window_lines)
    plan.columns = [_column(p, i) for i, p in enumerate(_dedupe(columns), 1)]

    fixed, done = geometry.fix(plan)
    plan = _split_crossings(fixed)
    plan, more = geometry.fix(plan)
    done += more
    _drop_crowded_openings(plan)
    stage(4)
    analysis = geometry.analyze(plan)
    labels, labelled = _labels(drawing, bbox, analysis.rooms, noise)
    plan.rooms = labels
    final = geometry.analyze(plan)
    result = Result(plan, notes)
    result.stats = {
        "walls": len(plan.walls),
        "openings": len(plan.openings),
        "columns": len(plan.columns),
        "rooms": len(final.rooms),
        "labelled": labelled,
        "issues": len(final.issues),
        "doors": sum(o.kind == "door" for o in plan.openings),
        "windows": sum(o.kind in ("window", "glazing") for o in plan.openings),
    }
    if done:
        result.notes.append("Исправлено при переводе: " + "; ".join(done))
    return result


# ---------------------------------------------------------------- колонны


def _column_shapes(segs: list[Seg], fills) -> list[Polygon]:  # type: ignore[no-untyped-def]
    out: list[Polygon] = []
    if segs:
        faces = polygonize(unary_union([LineString([s.a, s.b]) for s in segs]))
        merged = unary_union(list(faces))
        out += [p for p in walls._polys(merged) if walls._compact(p)]
    for f in fills:
        p = Polygon(f.ring).buffer(0)
        if not p.is_empty and walls._compact(p):
            out.append(p)
    return out


def _dedupe(columns: list[Polygon]) -> list[Polygon]:
    merged = unary_union([c.buffer(1) for c in columns]) if columns else Polygon()
    return [p for p in walls._polys(merged) if walls._compact(p)]


def _column(p: Polygon, i: int) -> Column:
    rect = p.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    e1 = (xs[1] - xs[0], ys[1] - ys[0])
    e2 = (xs[2] - xs[1], ys[2] - ys[1])
    w, d = math.hypot(*e1), math.hypot(*e2)
    angle = math.degrees(math.atan2(e1[1], e1[0])) % 180
    if angle > 90:
        angle -= 180
    round_ = p.area < 0.9 * rect.area and abs(w - d) < 0.1 * max(w, d)
    c = p.centroid
    return Column(
        id=f"c{i}",
        x=round(c.x, 1),
        y=round(c.y, 1),
        w=round(w),
        d=round(d),
        angle=round(angle, 2),
        round=round_,
    )


# ---------------------------------------------------------------- узлы и стены


def _graph(strips: list[walls.Strip]) -> tuple[Plan, set[str]]:
    lines = [LineString([s.a, s.b]) for s in strips if math.dist(s.a, s.b) > 1]
    src = [s for s in strips if math.dist(s.a, s.b) > 1]
    if not lines:
        return Plan(), set()
    tree = STRtree(lines)
    noded = unary_union(lines)
    pieces = [g for g in getattr(noded, "geoms", [noded]) if g.length > 0.5]
    nodes: dict[str, tuple[float, float]] = {}
    index: dict[tuple[int, int], str] = {}

    def node(p: tuple[float, float]) -> str:
        key = (round(p[0] / NODE), round(p[1] / NODE))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                k = index.get((key[0] + dx, key[1] + dy))
                if k is not None and math.dist(nodes[k], p) <= NODE:
                    return k
        k = f"n{len(nodes) + 1}"
        nodes[k] = (round(p[0], 1), round(p[1], 1))
        index[key] = k
        return k

    plan_walls: list[Wall] = []
    glazed: set[str] = set()
    for piece in pieces:
        a, b = piece.coords[0], piece.coords[-1]
        mid = piece.interpolate(0.5, normalized=True)
        j = min(
            (int(j) for j in tree.query(mid.buffer(1))),
            key=lambda j: lines[j].distance(mid),
            default=None,
        )
        if j is None:
            continue
        na, nb = node(a), node(b)
        if na == nb:
            continue
        s = src[j]
        wid = f"w{len(plan_walls) + 1}"
        if s.kind == "window":
            glazed.add(wid)
        plan_walls.append(
            Wall(
                id=wid,
                a=na,
                b=nb,
                thickness=max(s.t, 150) if s.kind == "window" else s.t,
                kind="bearing" if s.kind == "window" else s.kind,
            )
        )
    plan = Plan(nodes=nodes, walls=plan_walls)
    _prune(plan)
    return plan, glazed & {w.id for w in plan.walls}


def _prune(plan: Plan) -> None:
    """Висящие обрубки короче толщины стены — остатки углов, не стены."""
    changed = True
    while changed:
        changed = False
        degree: dict[str, int] = {}
        for w in plan.walls:
            degree[w.a] = degree.get(w.a, 0) + 1
            degree[w.b] = degree.get(w.b, 0) + 1
        keep = []
        for w in plan.walls:
            length = math.dist(plan.nodes[w.a], plan.nodes[w.b])
            if (
                (degree[w.a] == 1 or degree[w.b] == 1)
                and length < max(w.thickness, 150)
                and (degree[w.a] > 1 or degree[w.b] > 1)
            ):
                changed = True
                continue
            keep.append(w)
        plan.walls = keep
    used = {n for w in plan.walls for n in (w.a, w.b)}
    plan.nodes = {k: v for k, v in plan.nodes.items() if k in used}


def _openings(plan: Plan, gaps: list[walls.Gap]) -> None:
    lines = [LineString([plan.nodes[w.a], plan.nodes[w.b]]) for w in plan.walls]
    if not lines:
        return
    tree = STRtree(lines)
    for _i, g in enumerate(gaps, 1):
        c = Point((g.a[0] + g.b[0]) / 2, (g.a[1] + g.b[1]) / 2)
        width = math.dist(g.a, g.b)
        d = walls._unit(walls._sub(g.b, g.a))
        best = None
        for j in tree.query(c.buffer(g.t)):
            j = int(j)
            w = plan.walls[j]
            pa, pb = plan.nodes[w.a], plan.nodes[w.b]
            wd = walls._unit(walls._sub(pb, pa))
            if abs(walls._dot(wd, d)) < 0.98:
                continue
            dist = lines[j].distance(c)
            if dist <= g.t / 2 + 5 and (best is None or dist < best[0]):
                best = (dist, j)
        if best is None:
            continue
        w = plan.walls[best[1]]
        line = lines[best[1]]
        at = line.project(c)
        height, sill = HEIGHTS[g.kind]
        pa = plan.nodes[w.a]
        # петли и сторона — относительно направления стены a → b
        same = walls._dot(walls._unit(walls._sub(plan.nodes[w.b], pa)), d) > 0
        hinge = g.hinge if same else ("end" if g.hinge == "start" else "start")
        side = g.side if same else ("right" if g.side == "left" else "left")
        plan.openings.append(
            Opening(
                id=_uid("o", {o.id for o in plan.openings}),
                wall=w.id,
                kind=g.kind,
                at=round(at, 1),
                width=round(width),
                height=height,
                sill=sill,
                hinge=hinge,
                side=side,
            )
        )


def _in_gap(w: walls.Strip, gaps: list[walls.Gap]) -> bool:
    mid = Point((w.a[0] + w.b[0]) / 2, (w.a[1] + w.b[1]) / 2)
    return any(LineString([g.a, g.b]).distance(mid) <= g.t / 2 + 100 for g in gaps)


def _glazing(plan: Plan, glazed: set[str]) -> None:
    """Стена из линий окна — целиком проём: окно, а длинная — витраж."""
    n = len(plan.openings)
    for w in plan.walls:
        if w.id not in glazed:
            continue
        length = math.dist(plan.nodes[w.a], plan.nodes[w.b])
        if length < 400:
            continue
        kind = "glazing" if length > 3000 else "window"
        height, sill = HEIGHTS[kind]
        n += 1
        plan.openings.append(
            Opening(
                id=_uid("o", {o.id for o in plan.openings}),
                wall=w.id,
                kind=kind,
                at=round(length / 2, 1),
                width=round(length - 20),
                height=height,
                sill=sill,
            )
        )


def _bridge(plan: Plan, window_lines: list[LineString]) -> None:
    """Обрывы стен друг напротив друга — проём, который на чертеже не распознался (окно
    сложного рисунка, проём без дуги): между концами ставится стена с проёмом."""
    degree: dict[str, list[Wall]] = {}
    for w in plan.walls:
        degree.setdefault(w.a, []).append(w)
        degree.setdefault(w.b, []).append(w)
    ends = []
    for node, ws in degree.items():
        if len(ws) != 1:
            continue
        w = ws[0]
        other = w.b if w.a == node else w.a
        p, q = plan.nodes[node], plan.nodes[other]
        ends.append((node, p, walls._unit(walls._sub(p, q)), w))
    lines = [LineString([plan.nodes[w.a], plan.nodes[w.b]]) for w in plan.walls]
    tree = STRtree(lines) if lines else None
    window_tree = STRtree(window_lines) if window_lines else None
    # концы напротив — из дерева концов: на части листа их тысячи (R-059)
    end_tree = STRtree([Point(e[1]) for e in ends]) if ends else None
    used: set[str] = set()
    n = len(plan.openings)
    for node, p, d, w in sorted(ends, key=lambda e: e[0]):
        if node in used or end_tree is None:
            continue
        best = None
        near = sorted(int(k) for k in end_tree.query(Point(p), predicate="dwithin", distance=7000))
        for other, q, dq, wq in (ends[k] for k in near):
            if other == node or other in used:
                continue
            v = walls._sub(q, p)
            dist = math.hypot(*v)
            if not 300 <= dist <= 7000:
                continue
            u = (v[0] / dist, v[1] / dist)
            if walls._dot(u, d) < 0.94 or walls._dot(dq, (-u[0], -u[1])) < 0.94:
                continue
            # стены по обе стороны — на одной линии (или почти: грани ломаного фасада)
            off_q = abs(walls._dot(v, (-d[1], d[0])))
            off_p = abs(walls._dot(v, (-dq[1], dq[0])))
            if max(off_p, off_q) > max(w.thickness, wq.thickness):
                continue
            if best is None or dist < best[0]:
                best = (dist, other, q, wq)
        if best is None:
            continue
        dist, other, q, wq = best
        link = LineString([p, q])
        crossing = tree is not None and any(
            lines[int(j)].intersects(link)
            and plan.walls[int(j)] not in (w, wq)
            and lines[int(j)].intersection(link).distance(Point(p)) > 1
            and lines[int(j)].intersection(link).distance(Point(q)) > 1
            for j in tree.query(link)
        )
        if crossing:
            continue
        used.update((node, other))
        wid = _uid("b", {w.id for w in plan.walls})
        plan.walls.append(
            Wall(id=wid, a=node, b=other, thickness=min(w.thickness, wq.thickness), kind=w.kind)
        )
        band = link.buffer(min(w.thickness, wq.thickness) / 2 + 100, cap_style="flat")
        glass = (
            window_tree is not None
            and sum(window_lines[int(j)].intersection(band).length for j in window_tree.query(band))
            > 0.6 * dist
        )
        kind = (
            ("glazing" if dist > 3000 else "window")
            if glass
            else ("door" if dist <= 1300 else "passage")
        )
        height, sill = HEIGHTS[kind]
        n += 1
        plan.openings.append(
            Opening(
                id=_uid("o", {o.id for o in plan.openings}),
                wall=wid,
                kind=kind,
                at=round(dist / 2, 1),
                width=round(dist - 20),
                height=height,
                sill=sill,
            )
        )
    _bridge_to_walls(plan, used)


def _bridge_to_walls(plan: Plan, used: set[str]) -> None:
    """Обрыв стены, смотрящий на другую стену в шаге двери, — дверь у угла: стена доводится
    до той стены, в просвете — проём."""
    degree: dict[str, list[Wall]] = {}
    for w in plan.walls:
        degree.setdefault(w.a, []).append(w)
        degree.setdefault(w.b, []).append(w)
    n = len(plan.openings)
    # стены на пути луча — из дерева; разрезанные и новые стены — в конце списка, их мало
    first = len(plan.walls)
    tree = STRtree([LineString([plan.nodes[w.a], plan.nodes[w.b]]) for w in plan.walls]) \
        if plan.walls else None
    for node, ws in list(degree.items()):
        if len(ws) != 1 or node in used or tree is None:
            continue
        w = ws[0]
        other = w.b if w.a == node else w.a
        p, q = plan.nodes[node], plan.nodes[other]
        d = walls._unit(walls._sub(p, q))
        ray = LineString([p, walls._along(p, d, 2200)])
        best = None
        crossed = sorted(int(k) for k in tree.query(ray))
        for v in [plan.walls[k] for k in crossed] + plan.walls[first:]:
            if v is w or node in (v.a, v.b):
                continue
            line = LineString([plan.nodes[v.a], plan.nodes[v.b]])
            hit = line.intersection(ray)
            if hit.is_empty or hit.geom_type != "Point":
                continue
            dist = math.dist(p, (hit.x, hit.y))
            if best is None or dist < best[0]:
                best = (dist, v, (hit.x, hit.y))
        if best is None or not 250 <= best[0] <= 2200:
            continue
        dist, v, hit = best
        va, vb = plan.nodes[v.a], plan.nodes[v.b]
        at = math.dist(va, hit)
        if at < 50 or at > math.dist(va, vb) - 50:
            target = v.a if at < 50 else v.b
        else:
            target = _uid("t", set(plan.nodes))
            plan.nodes[target] = (round(hit[0], 1), round(hit[1], 1))
            geometry._split_wall(plan, v, target, at)
        wid = _uid("d", {w.id for w in plan.walls})
        plan.walls.append(Wall(id=wid, a=node, b=target, thickness=w.thickness, kind=w.kind))
        kind = "door" if dist <= 1300 else "passage"
        height, sill = HEIGHTS[kind]
        width = max(dist - v.thickness / 2 - 20, 200)
        n += 1
        plan.openings.append(
            Opening(
                id=_uid("o", {o.id for o in plan.openings}),
                wall=wid,
                kind=kind,
                at=round(width / 2 + 10, 1),
                width=round(width),
                height=height,
                sill=sill,
            )
        )
        used.add(node)


def _drop_overlaps(plan: Plan) -> bool:
    """Две стены на одной линии внахлёст: короткая, лежащая в длинной, убирается, её проёмы
    переходят в длинную."""
    pairs = [i.ids for i in geometry.check(plan) if i.code == "double_wall"]
    gone: set[str] = set()
    by_id = {w.id: w for w in plan.walls}
    for a, b in pairs:
        if a in gone or b in gone:
            continue
        wa, wb = by_id[a], by_id[b]
        la = LineString([plan.nodes[wa.a], plan.nodes[wa.b]])
        lb = LineString([plan.nodes[wb.a], plan.nodes[wb.b]])
        short, long_, ls, ll = (wa, wb, la, lb) if la.length <= lb.length else (wb, wa, lb, la)
        if (
            ls.length
            and ll.buffer(max(long_.thickness, short.thickness) / 2 + 5).intersection(ls).length
            < 0.9 * ls.length
        ):
            continue
        gone.add(short.id)
        for o in plan.openings:
            if o.wall == short.id:
                c = ls.interpolate(o.at)
                o.wall, o.at = long_.id, round(ll.project(c), 1)
    if gone:
        plan.walls = [w for w in plan.walls if w.id not in gone]
    return bool(gone)


def _drop_crowded_openings(plan: Plan) -> None:
    """Проёмы, которые не разошлись по стене, — остаётся больший."""
    for issue in [i for i in geometry.check(plan) if i.code == "openings_overlap"]:
        ops = [o for o in plan.openings if o.id in issue.ids]
        if len(ops) == 2:
            smaller = min(ops, key=lambda o: o.width)
            plan.openings = [o for o in plan.openings if o.id != smaller.id]


def _split_crossings(plan: Plan) -> Plan:
    """Стены, пересекающиеся не в узле, режутся в точке пересечения."""
    for _ in range(3):
        if _drop_overlaps(plan):
            plan, _ = geometry.fix(plan)
        issues = [i for i in geometry.check(plan) if i.code == "crossing"]
        if not issues:
            break
        for issue in issues:
            point = (issue.x, issue.y)
            node = _uid("x", set(plan.nodes))
            plan.nodes[node] = point
            for wid in issue.ids:
                w = next((x for x in plan.walls if x.id == wid), None)
                if w is None:
                    continue
                line = LineString([plan.nodes[w.a], plan.nodes[w.b]])
                at = line.project(Point(point))
                if 1 < at < line.length - 1:
                    geometry._split_wall(plan, w, node, at)
        plan, _ = geometry.fix(plan)
    return plan


# ---------------------------------------------------------------- подписи помещений


def _labels(
    drawing: Drawing,
    bbox,
    rooms: list[geometry.RoomShape],  # type: ignore[no-untyped-def]
    noise: list[list[Seg]],
) -> tuple[list[RoomLabel], int]:
    """Номер и название помещения — из текстов в нём. Тексты слоёв дверей, окон и стен — марки,
    а не номера; название в несколько строк — целиком (R-063)."""
    found: list[tuple[captions.Line, str]] = []
    for line in captions.lines([t for t in drawing.texts if _inside(bbox, (t.x, t.y))]):
        if not labels_layer(line.layer):
            continue
        layer = role(line.layer)
        kind = text_kind(line.text)
        if kind == "number" and layer in NOT_NUMBERS:
            kind = "none"
        found.append((line, kind))
    found += [(captions.Line("", x, y, 0, text), "number") for x, y, text in glyphs.read(noise)]
    out: list[RoomLabel] = []
    labelled = 0
    for i, room in enumerate(rooms, 1):
        inside = [(t, k) for t, k in found if k in ("number", "name", "area")
                  and room.polygon.contains(Point(t.x, t.y))]
        numbers = [t for t, k in inside if k == "number"]
        blocks = captions.blocks([t for t, k in inside if k == "name"])
        names = [" ".join(t.text for t in b) for b in blocks]
        heads = [b[0] for b in blocks]
        cx, cy = room.polygon.representative_point().coords[0]
        # номер — тот, рядом с которым название или площадь; без них — верхний (под ним
        # обычно площадь или название)
        near = [t for t, k in inside if k in ("name", "area")]
        number = (min(numbers, key=lambda t: min(math.dist((t.x, t.y), (n.x, n.y)) for n in near))
                  if near and numbers else max(numbers, key=lambda t: t.y, default=None))
        at = (number.x, number.y) if number else (cx, cy)
        name = min(range(len(heads)), key=lambda j: math.dist((heads[j].x, heads[j].y), at),
                   default=None)
        anchor = number or (heads[name] if name is not None else None)
        x, y = (anchor.x, anchor.y) if anchor else (cx, cy)
        if number:
            labelled += 1
        out.append(
            RoomLabel(
                id=f"new-{i}",
                x=round(x, 1),
                y=round(y, 1),
                number=(number.text if number else "")[:30],
                name=(names[name] if name is not None else "")[:200],
            )
        )
    return out, labelled
