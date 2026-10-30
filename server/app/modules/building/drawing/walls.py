"""Стены из линий чертежа.

1. Линии стен (без проёмов, подписей и мелочи) сшиваются в узлах, короткие разрывы
   замыкаются; из получившихся многоугольников тонкие — это тело стен; к нему добавляются
   сплошные заливки стен. Так двойные линии, стены из нескольких слоёв (бетон, утеплитель,
   облицовка) и стены, обведённые контуром, становятся одной массой.
2. Небольшие плотные куски массы — колонны.
3. Каждые две противоположные грани массы на расстоянии толщины стены дают полосу; её
   середина — ось стены, расстояние — толщина.
4. Полосы на одной линии сливаются; разрыв между ними шириной с дверь — проём: окно, если
   в разрыве линии окна, дверь, если рядом дуга открывания, иначе проход.
5. Концы стен продлеваются до стен, у которых они обрываются (углы, примыкания), оси
   режутся в пересечениях — получаются узлы и стены плана.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import STRtree, unary_union
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize

from app.modules.building.drawing.read import Arc, Fill, Pt, Seg

MIN_T, MAX_T = 50.0, 800.0  # какая бывает толщина стены, мм
SNAP = 30.0  # разрыв линий, который замыкается
NOISE = 1500.0  # связная группа линий меньше — не стена (подпись, знак)
PARALLEL = 0.985  # cos угла между противоположными гранями
OVERLAP = 30.0
DOOR_MIN, DOOR_MAX, WIDE_MAX = 500.0, 3000.0, 7000.0
REACH = 600.0  # насколько конец стены может не доходить до стены, к которой примыкает


@dataclass
class Strip:
    a: Pt
    b: Pt
    t: float
    kind: str  # bearing | partition


@dataclass
class Gap:
    """Проём: на линии стены между a и b."""

    a: Pt
    b: Pt
    t: float
    kind: str  # door | window | passage | glazing
    hinge: str = "start"
    side: str = "left"


@dataclass
class Walls:
    strips: list[Strip]
    gaps: list[Gap]
    columns: list[Polygon]
    noise: list[list[Seg]] = field(default_factory=list)  # мелкие группы — подписи линиями


def _polys(g) -> list[Polygon]:  # type: ignore[no-untyped-def]
    if g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def _unit(v: Pt) -> Pt:
    n = math.hypot(*v) or 1.0
    return (v[0] / n, v[1] / n)


def _sub(a: Pt, b: Pt) -> Pt:
    return (a[0] - b[0], a[1] - b[1])


def _dot(a: Pt, b: Pt) -> float:
    return a[0] * b[0] + a[1] * b[1]


def _along(p: Pt, d: Pt, k: float) -> Pt:
    return (p[0] + d[0] * k, p[1] + d[1] * k)


def is_thin(poly: Polygon, max_t: float = MAX_T) -> bool:
    return poly.buffer(-max_t / 2, join_style="mitre").is_empty


# ---------------------------------------------------------------- 1. масса стен


def lines_of(segs: list[Seg]) -> np.ndarray:
    """Отрезки — массивом линий shapely: сотни тысяч за доли секунды (R-059)."""
    if not segs:
        return np.empty(0, dtype=object)
    return shapely.linestrings(np.array([(s.a, s.b) for s in segs], dtype=float))


def _components(segs: list[Seg]) -> list[list[int]]:
    """Связные группы отрезков (касание в пределах SNAP). Пары соседей ищет одним запросом
    дерево, группы сливаются по массивам: на сотнях тысяч отрезков — секунды, а не минуты
    (R-059)."""
    if not segs:
        return []
    lines = lines_of(segs)
    left, right = STRtree(lines).query(lines, predicate="dwithin", distance=SNAP)
    keep = left < right
    left, right = left[keep], right[keep]
    parent = np.arange(len(segs))
    while True:
        a, b = parent[left], parent[right]
        differ = a != b
        if not differ.any():
            break
        # корень с большим номером подвешивается к меньшему, затем пути сжимаются до корней
        np.minimum.at(parent, np.maximum(a[differ], b[differ]), np.minimum(a[differ], b[differ]))
        while True:
            up = parent[parent]
            if np.array_equal(up, parent):
                break
            parent = up
    groups: dict[int, list[int]] = {}
    for i, root in enumerate(parent.tolist()):
        groups.setdefault(root, []).append(i)
    return list(groups.values())


def _extent(segs: list[Seg]) -> float:
    xs = [p[0] for s in segs for p in (s.a, s.b)]
    ys = [p[1] for s in segs for p in (s.a, s.b)]
    return math.hypot(max(xs) - min(xs), max(ys) - min(ys))


def _compact(poly: Polygon, aspect: float = 3.0) -> bool:
    """Колонна: небольшая, плотная, без вытянутости."""
    if poly.is_empty or poly.area < 30_000:  # меньше 0,03 м²
        return False
    rect = poly.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    sides = sorted({round(math.dist((xs[i], ys[i]), (xs[i + 1], ys[i + 1]))) for i in range(4)})
    long, short = sides[-1], sides[0]
    return long <= 1500 and long <= aspect * max(short, 1) and poly.area >= 0.75 * rect.area


def _close_gaps(lines: list[LineString]) -> list[LineString]:
    """Висящий конец, не доходящий до линии на SNAP, дотягивается до неё. Концы и соседей
    ищет дерево разом для всех линий (R-059)."""
    if not lines:
        return lines
    arr = np.array(lines, dtype=object)
    tree = STRtree(arr)
    coords = shapely.get_coordinates(arr)
    sizes = shapely.get_num_coordinates(arr)
    last = np.cumsum(sizes) - 1
    ends = shapely.points(np.concatenate([coords[last - sizes + 1], coords[last]]))
    owner = np.tile(np.arange(len(arr)), 2)
    # конец, которого касается ещё что-то, не висит
    pi, lj = tree.query(ends, predicate="dwithin", distance=0.5)
    touched = np.zeros(len(ends), dtype=bool)
    touched[pi[lj != owner[pi]]] = True
    free = np.flatnonzero(~touched)
    pi, lj = tree.query(ends[free], predicate="dwithin", distance=SNAP)
    pi = free[pi]
    other = lj != owner[pi]
    pi, lj = pi[other], lj[other]
    dist = shapely.distance(ends[pi], arr[lj])
    far = dist >= 0.5
    pi, lj, dist = pi[far], lj[far], dist[far]
    if not len(pi):
        return lines
    # у каждого конца — ближайшая линия
    order = np.lexsort((dist, pi))
    pi, lj = pi[order], lj[order]
    first = np.r_[True, pi[1:] != pi[:-1]]
    pi, lj = pi[first], lj[first]
    to = shapely.line_interpolate_point(arr[lj], shapely.line_locate_point(arr[lj], ends[pi]))
    extra = shapely.linestrings(np.stack([shapely.get_coordinates(ends[pi]),
                                          shapely.get_coordinates(to)], axis=1))
    return lines + list(extra)


def mass(segs: list[Seg], fills: list[Fill]) -> tuple[Polygon, list[Polygon], list[list[Seg]]]:
    """Тело стен, колонны, отброшенные мелкие группы линий."""
    groups = _components(segs)
    keep: list[Seg] = []
    columns: list[Polygon] = []
    noise: list[list[Seg]] = []
    for g in groups:
        part = [segs[i] for i in g]
        if _extent(part) >= NOISE:
            keep += part
            continue
        # колонна не меньше 0,03 м² и не вытянута больше чем втрое — значит, не уже 100 мм:
        # значки, буквы, точки отсеиваются без построения граней
        xs = [p[0] for s in part for p in (s.a, s.b)]
        ys = [p[1] for s in part for p in (s.a, s.b)]
        if len(part) < 3 or min(max(xs) - min(xs), max(ys) - min(ys)) < 100:
            noise.append(part)
            continue
        faces = list(polygonize(unary_union([LineString([s.a, s.b]) for s in part])))
        outline = unary_union(faces) if faces else Polygon()
        if faces and isinstance(outline, Polygon) and _compact(outline):
            columns.append(outline)
        else:
            noise.append(part)
    lines = [LineString([s.a, s.b]) for s in keep if math.dist(s.a, s.b) > 0.5]
    noded = unary_union(_close_gaps(lines)) if lines else MultiLineString()
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(noded)))
    faces = faces[shapely.area(faces) > 1000]
    # тонкие грани — стены: сжатые на половину наибольшей толщины, они исчезают
    thin = list(faces[shapely.is_empty(shapely.buffer(faces, -MAX_T / 2, join_style="mitre"))])
    thin += _leftovers(keep, thin)
    thin += [
        p
        for p in (Polygon(f.ring).buffer(0) for f in fills if len(f.ring) >= 3)
        if not p.is_empty and p.area > 1000 and is_thin(p)
    ]
    body = unary_union(thin).buffer(1, join_style="mitre").buffer(-1, join_style="mitre")
    walls: list[Polygon] = []
    for p in _polys(body):
        # кусок тела стен — колонна, только если почти квадратный: короткий простенок у
        # двери тоже мал, но вытянут
        if _compact(p, aspect=1.5):
            columns.append(p)
        else:
            walls.append(p)
    return unary_union(walls) if walls else Polygon(), columns, noise


LONE_T = 100.0  # толщина стены, нарисованной одной линией


def _on_faces(lines: np.ndarray, faces: list[Polygon]) -> np.ndarray:
    """Какие линии лежат на контурах граней (в 3 мм): все их точки через 100 мм у контура."""
    if not faces or not len(lines):
        return np.zeros(len(lines), dtype=bool)
    rings = STRtree(shapely.get_exterior_ring(np.array(faces, dtype=object)))
    counts = np.ceil(shapely.length(lines) / 100).astype(int) + 1
    owner = np.repeat(np.arange(len(lines)), counts)
    starts = np.cumsum(counts) - counts
    frac = (np.arange(len(owner)) - starts[owner]) / (counts[owner] - 1)
    points = shapely.line_interpolate_point(lines[owner], frac, normalized=True)
    near = np.zeros(len(points), dtype=bool)
    near[rings.query(points, predicate="dwithin", distance=3)[0]] = True
    return np.logical_and.reduceat(near, starts)


def _leftovers(segs: list[Seg], faces: list[Polygon]) -> list[Polygon]:
    """Линии стен, не ставшие гранью замкнутого тела: пары параллельных на толщине стены —
    незамкнутая двойная стена; одиночная длинная — стена в одну линию. Пары ищет дерево и
    проверяют массивы: в части листа их бывают миллионы (R-059)."""
    long = [s for s in segs if math.dist(s.a, s.b) >= 200]
    lines = lines_of(long)
    left = np.flatnonzero(~_on_faces(lines, faces))
    if not len(left):
        return []
    lines = lines[left]
    a = np.array([long[k].a for k in left], dtype=float)
    b = np.array([long[k].b for k in left], dtype=float)
    length = np.hypot(*(b - a).T)
    d = (b - a) / length[:, None]
    n = np.stack([-d[:, 1], d[:, 0]], axis=1)
    i, j = STRtree(lines).query(lines, predicate="dwithin", distance=MAX_T)
    i, j = i[i < j], j[i < j]
    dot = lambda u, v: (u * v).sum(axis=1)  # noqa: E731
    t = dot(a[j] - a[i], n[i])
    s0 = np.minimum(dot(a[j] - a[i], d[i]), dot(b[j] - a[i], d[i])).clip(min=0)
    s1 = np.minimum(np.maximum(dot(a[j] - a[i], d[i]), dot(b[j] - a[i], d[i])), length[i])
    pair = (
        (np.abs(dot(d[i], d[j])) >= PARALLEL)
        & (np.abs(t) >= MIN_T)
        & (np.abs(t) <= MAX_T)
        & (np.abs(dot(b[j] - a[i], n[i]) - t) <= 5)
        & (s1 - s0 >= 200)
    )
    i, t, s0, s1 = i[pair], t[pair], s0[pair], s1[pair]
    p0 = a[i] + d[i] * s0[:, None]
    p1 = a[i] + d[i] * s1[:, None]
    shift = n[i] * t[:, None]
    out = list(shapely.polygons(np.stack([p0, p1, p1 + shift, p0 + shift], axis=1)))
    paired = np.zeros(len(left), dtype=bool)
    paired[i] = paired[j[pair]] = True
    # одиночная линия, пересекающая стену, — не стена (засечка, знак разрыва)
    lone = np.flatnonzero(~paired & (length >= 600))
    if len(lone) and faces:
        k, f = STRtree(np.array(faces, dtype=object)).query(lines[lone], predicate="intersects")
        crossed = np.zeros(len(lone))
        np.add.at(crossed, k, shapely.length(shapely.intersection(
            lines[lone][k], np.array(faces, dtype=object)[f])))
        lone = lone[crossed <= 30]
    out += list(shapely.buffer(lines[lone], LONE_T / 2, cap_style="flat"))
    return out


# ---------------------------------------------------------------- 3. оси стен


def strips(body, kind_of) -> list[Strip]:  # type: ignore[no-untyped-def]
    """Середины между противоположными гранями тела стен."""
    edges: list[tuple[Pt, Pt]] = []
    for p in _polys(body):
        p = orient(p.simplify(2), 1.0)  # тело слева от каждой грани
        for ring in [p.exterior, *p.interiors]:
            cs = list(ring.coords)
            edges += [(a, b) for a, b in zip(cs, cs[1:], strict=False) if math.dist(a, b) > OVERLAP]
    if not edges:
        return []
    lines = [LineString(e) for e in edges]
    tree = STRtree(lines)
    near = body.buffer(5)
    out: list[Strip] = []
    for i, (a, b) in enumerate(edges):
        d = _unit(_sub(b, a))
        n = (-d[1], d[0])  # внутрь тела
        length = math.dist(a, b)
        for j in tree.query(lines[i].buffer(MAX_T)):
            j = int(j)
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
            if s1 - s0 < OVERLAP:
                continue
            p0, p1 = _along(a, d, s0), _along(a, d, s1)
            band = Polygon([p0, p1, _along(p1, n, t), _along(p0, n, t)])
            if band.intersection(near).area < 0.9 * band.area:
                continue  # пустота между двумя стенами
            h = (n[0] * t / 2, n[1] * t / 2)
            ma, mb = (p0[0] + h[0], p0[1] + h[1]), (p1[0] + h[0], p1[1] + h[1])
            out.append(
                Strip(
                    ma,
                    mb,
                    round(t / 5) * 5,
                    kind_of(Point((ma[0] + mb[0]) / 2, (ma[1] + mb[1]) / 2), t),
                )
            )
    return out


# ---------------------------------------------------------------- 4. линии стен и проёмы


@dataclass
class _Line:
    d: Pt
    p: Pt
    t: float
    kind: str
    spans: list[tuple[float, float, float]] = field(default_factory=list)


def join(
    segments: list[Strip],
    body,
    windows: list[LineString],
    arcs: list[Arc],  # type: ignore[no-untyped-def]
) -> tuple[list[Strip], list[Gap]]:
    lines: list[_Line] = []
    for s in segments:
        d = _unit(_sub(s.b, s.a))
        if d[0] < -1e-9 or (abs(d[0]) < 1e-9 and d[1] < 0):
            d = (-d[0], -d[1])
        for g in lines:
            off = _sub(s.a, g.p)
            if (
                abs(g.d[0] * d[1] - g.d[1] * d[0]) < 0.02
                and abs(g.d[0] * off[1] - g.d[1] * off[0]) < 20
                and abs(g.t - s.t) <= 30
            ):
                break
        else:
            g = _Line(d, s.a, s.t, s.kind)
            lines.append(g)
        k0, k1 = sorted((_dot(_sub(s.a, g.p), g.d), _dot(_sub(s.b, g.p), g.d)))
        g.spans.append((k0, k1, s.t))
    near = body.buffer(10)
    window_tree = STRtree(windows) if windows else None
    out: list[Strip] = []
    gaps: list[Gap] = []
    for g in lines:
        spans = sorted(g.spans)
        runs: list[list[float]] = [[spans[0][0], spans[0][1]]]
        for k0, k1, _ in spans[1:]:
            cur = runs[-1]
            if k0 <= cur[1] + 1:
                cur[1] = max(cur[1], k1)
                continue
            gap = LineString([_along(g.p, g.d, cur[1]), _along(g.p, g.d, k0)])
            if gap.length < MAX_T and near.contains(gap):
                cur[1] = max(cur[1], k1)  # стена продолжается (утолщение, стык)
                continue
            runs.append([k0, k1])
        # разрывы между отрезками одной линии — проёмы
        merged: list[list[float]] = [runs[0]]
        for run in runs[1:]:
            prev = merged[-1]
            width = run[0] - prev[1]
            a, b = _along(g.p, g.d, prev[1]), _along(g.p, g.d, run[0])
            kind = _gap_kind(a, b, g, width, window_tree, windows, arcs, near)
            if kind is None:
                merged.append(run)
                continue
            gaps.append(Gap(a, b, g.t, kind[0], kind[1], kind[2]))
            prev[1] = run[1]
        for k0, k1 in merged:
            if k1 - k0 >= max(g.t, 100):  # короче толщины — выступ у угла, не стена
                out.append(Strip(_along(g.p, g.d, k0), _along(g.p, g.d, k1), g.t, g.kind))
    return out, gaps


def _gap_kind(
    a: Pt,
    b: Pt,
    g: _Line,
    width: float,
    tree,
    windows,
    arcs,
    near,  # type: ignore[no-untyped-def]
) -> tuple[str, str, str] | None:
    if width < DOOR_MIN or width > WIDE_MAX:
        return None
    n = (-g.d[1], g.d[0])
    rect = Polygon(
        [
            _along(a, n, g.t / 2 + 50),
            _along(b, n, g.t / 2 + 50),
            _along(b, n, -g.t / 2 - 50),
            _along(a, n, -g.t / 2 - 50),
        ]
    )
    if rect.intersection(near).area > 0.3 * rect.area:
        return None  # в разрыве — другая стена
    has_window = tree is not None and any(
        windows[int(j)].intersection(rect).length > width * 0.5 for j in tree.query(rect)
    )
    if has_window:
        return ("window" if width <= 3000 else "glazing", "start", "left")
    if width > DOOR_MAX:
        return None
    # дуга открывания: центр у одного края проёма, радиус — около ширины
    for arc in arcs:
        if not 0.6 * width <= arc.radius <= 1.25 * width:
            continue
        for hinge, p in (("start", a), ("end", b)):
            if math.dist(arc.center, p) <= g.t / 2 + 150:
                mid = math.radians(arc.start + ((arc.end - arc.start) % 360) / 2)
                tip = (
                    arc.center[0] + arc.radius * math.cos(mid),
                    arc.center[1] + arc.radius * math.sin(mid),
                )
                side = "left" if _dot(_sub(tip, arc.center), n) > 0 else "right"
                return ("door", hinge, side)
    return ("door" if width <= 1300 else "passage", "start", "left")


# ---------------------------------------------------------------- 5. углы и примыкания


def _meet(p: Pt, d: Pt, a: Pt, b: Pt) -> tuple[float, float] | None:
    e = _sub(b, a)
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9 * (math.hypot(*e) or 1):
        return None
    w = _sub(a, p)
    u = (w[0] * e[1] - w[1] * e[0]) / den
    s = (w[0] * d[1] - w[1] * d[0]) / den
    return u, s * math.hypot(*e)


def extend(segments: list[Strip], body) -> list[Strip]:  # type: ignore[no-untyped-def]
    """Каждый конец продлевается сквозь тело стены до ближайшей стены, до которой он не дошёл."""
    near = body.buffer(30)
    lines = [LineString([s.a, s.b]) for s in segments]
    tree = STRtree(lines)
    out = [Strip(s.a, s.b, s.t, s.kind) for s in segments]
    for i, s in enumerate(segments):
        for end in (0, 1):
            p, q = (s.a, s.b) if end == 0 else (s.b, s.a)
            d = _unit(_sub(p, q))
            best = None
            for j in tree.query(Point(p).buffer(MAX_T + REACH)):
                j = int(j)
                if j == i:
                    continue
                o = segments[j]
                m = _meet(p, d, o.a, o.b)
                if m is None:
                    continue
                u, at = m
                reach = max(s.t, o.t) / 2 + REACH
                length = math.dist(o.a, o.b)
                if not -1 <= u <= reach or not -(s.t / 2 + REACH) <= at <= length + s.t / 2 + REACH:
                    continue
                if best is None or u < best:
                    to = _along(p, d, u)
                    if u <= 1 or near.contains(LineString([p, to])):
                        best = u
            if best is not None and best > 0:
                moved = _along(p, d, best)
                if end == 0:
                    out[i].a = moved
                else:
                    out[i].b = moved
    return out
