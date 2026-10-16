"""Геометрия плана: помещения из замкнутых стен (5.1.4 п. 4), проверка плана (5.1.5) и её
автоматическое исправление. Считается только здесь — редактор спрашивает сервер, поэтому
то, что видно в редакторе, и то, что сохраняется, не расходится."""

import math
from dataclasses import dataclass, field

from shapely import STRtree, unary_union
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from app.modules.building.plan import Opening, Plan, Wall

MIN_WALL = 5.0  # мм: стена короче — ошибка (5.1.5)
NODE_TOL = 5.0  # мм: узлы ближе — один узел
ON_LINE = 1.0  # мм: точка на линии стены
ARC_STEP = 100.0  # мм: шаг разбиения дуги


@dataclass
class Issue:
    code: str
    message: str
    x: float
    y: float
    ids: list[str]
    auto: bool  # исправляется автоматически

    def view(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "x": round(self.x, 1),
                "y": round(self.y, 1), "ids": self.ids, "auto": self.auto}


@dataclass
class RoomShape:
    polygon: Polygon
    labels: list[str] = field(default_factory=list)

    @property
    def area_m2(self) -> float:
        return round(self.polygon.area / 1e6, 2)

    def outline(self) -> list[list[float]]:
        return [[round(x, 1), round(y, 1)] for x, y in self.polygon.exterior.coords[:-1]]

    def anchor(self) -> tuple[float, float]:
        p = self.polygon.representative_point()
        return round(p.x, 1), round(p.y, 1)


@dataclass
class Analysis:
    rooms: list[RoomShape]
    issues: list[Issue]
    # контуры перекрытий: всё, что обнесено наружными стенами (для 3D и печати)
    slabs: list[Polygon]


# ---------------------------------------------------------------- стены

def arc_points(a: tuple[float, float], b: tuple[float, float], bulge: float,
               step: float = ARC_STEP) -> list[tuple[float, float]]:
    """Точки осевой линии стены от a до b (дуга — по bulge, как в DXF)."""
    if abs(bulge) < 1e-9:
        return [a, b]
    (ax, ay), (bx, by) = a, b
    chord = math.hypot(bx - ax, by - ay)
    if chord < 1e-9:
        return [a, b]
    theta = 4 * math.atan(bulge)  # центральный угол со знаком
    radius = chord / (2 * math.sin(abs(theta) / 2))
    # центр: от середины хорды по нормали
    mx, my = (ax + bx) / 2, (ay + by) / 2
    dx, dy = (bx - ax) / chord, (by - ay) / chord
    h = radius * math.cos(theta / 2)
    # bulge > 0: дуга выгнута вправо от a → b, центр — влево (при |θ| < 180°)
    sign = 1 if bulge > 0 else -1
    cx, cy = mx + (-dy) * h * sign, my + dx * h * sign
    start = math.atan2(ay - cy, ax - cx)
    sweep = theta  # bulge > 0 — против часовой, как в DXF
    n = max(8, int(abs(sweep) * radius / step) + 1)
    return [(cx + radius * math.cos(start + sweep * i / n),
             cy + radius * math.sin(start + sweep * i / n)) for i in range(n + 1)]


def centerline(plan: Plan, wall: Wall) -> LineString:
    a, b = plan.nodes[wall.a], plan.nodes[wall.b]
    return LineString(arc_points(a, b, wall.bulge))


def wall_length(plan: Plan, wall: Wall) -> float:
    return centerline(plan, wall).length


def wall_body(plan: Plan, wall: Wall) -> BaseGeometry:
    return centerline(plan, wall).buffer(wall.thickness / 2, cap_style="flat",
                                         join_style="mitre")


def _valid_walls(plan: Plan) -> list[Wall]:
    return [w for w in plan.walls if w.a in plan.nodes and w.b in plan.nodes and w.a != w.b]


# ---------------------------------------------------------------- помещения

def analyze(plan: Plan) -> Analysis:
    walls = _valid_walls(plan)
    bodies = [wall_body(plan, w) for w in walls if wall_length(plan, w) > 0]
    # узлы — кругом толщиной в самую толстую примыкающую стену: углы смыкаются
    thickest: dict[str, float] = {}
    for w in walls:
        for n in (w.a, w.b):
            thickest[n] = max(thickest.get(n, 0), w.thickness)
    bodies += [Point(plan.nodes[n]).buffer(t / 2, quad_segs=8) for n, t in thickest.items()]
    union = unary_union(bodies) if bodies else Polygon()
    parts = [union] if isinstance(union, Polygon) else list(getattr(union, "geoms", []))
    rooms: list[RoomShape] = []
    slabs: list[Polygon] = []
    parts = [p for p in parts if isinstance(p, Polygon) and not p.is_empty]
    shells = [Polygon(p.exterior) for p in parts]
    slabs = _slabs(union)
    for part in parts:
        for ring in part.interiors:
            hole = Polygon(ring)
            # стены-острова внутри помещения (ядро, колонна стен) — не его площадь
            islands = [s for s in shells if s.within(hole)]
            if islands:
                hole = hole.difference(unary_union(islands))
                if not isinstance(hole, Polygon):
                    hole = max(getattr(hole, "geoms", []), key=lambda g: g.area,
                               default=Polygon())
            if hole.area >= 0.25e6:  # меньше 0,25 м² — щель между стенами, не помещение
                rooms.append(RoomShape(hole))
    for label in plan.rooms:
        point = Point(label.x, label.y)
        for room in rooms:
            if room.polygon.contains(point):
                room.labels.append(label.id)
                break
    return Analysis(rooms=rooms, issues=check(plan, rooms), slabs=slabs)


SLAB_GAP = 2500.0  # мм: разрывы в наружных стенах до 2 × столько перекрытие закрывает


def _slabs(union: BaseGeometry) -> list[Polygon]:
    """Перекрытие — очертание этажа: всё, что обнесено стенами, с закрытыми разрывами
    фасада (проём без распознанной стены, недорисованный угол), без дыр внутри."""
    if union.is_empty:
        return []
    closed = union.buffer(SLAB_GAP, quad_segs=2).buffer(-SLAB_GAP, quad_segs=2)
    out = []
    for p in (closed.geoms if hasattr(closed, "geoms") else [closed]):
        if isinstance(p, Polygon) and not p.is_empty and p.area > 1e6:
            out.append(Polygon(p.exterior))
    return out


# ---------------------------------------------------------------- проверка (5.1.5)

def _opening_span(plan: Plan, op: Opening) -> tuple[float, float]:
    return op.at - op.width / 2, op.at + op.width / 2


def check(plan: Plan, rooms: list[RoomShape] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    walls = {w.id: w for w in plan.walls}

    for w in plan.walls:
        if w.a not in plan.nodes or w.b not in plan.nodes:
            issues.append(Issue("broken_wall", "Стена без узла", 0, 0, [w.id], True))
            continue
        line = centerline(plan, w)
        if line.length < MIN_WALL:
            p = line.interpolate(0.5, normalized=True)
            issues.append(Issue("short_wall", f"Стена короче {MIN_WALL:.0f} мм", p.x, p.y,
                                [w.id], True))

    good = [w for w in _valid_walls(plan) if wall_length(plan, w) >= MIN_WALL]
    lines = [centerline(plan, w) for w in good]
    tree = STRtree(lines)
    seen: set[tuple[str, str]] = set()
    for i, w in enumerate(good):
        for j in tree.query(lines[i]):
            j = int(j)
            if j <= i:
                continue
            v = good[j]
            key = (w.id, v.id)
            if key in seen:
                continue
            seen.add(key)
            shared = {w.a, w.b} & {v.a, v.b}
            if {w.a, w.b} == {v.a, v.b} and abs(w.bulge) < 1e-9 and abs(v.bulge) < 1e-9:
                p = lines[i].interpolate(0.5, normalized=True)
                issues.append(Issue("double_wall", "Двойная стена", p.x, p.y,
                                    [w.id, v.id], True))
                continue
            inter = lines[i].intersection(lines[j])
            if inter.is_empty:
                continue
            if inter.geom_type in ("LineString", "MultiLineString") and inter.length > MIN_WALL:
                p = inter.interpolate(0.5, normalized=True)
                issues.append(Issue("double_wall", "Двойная стена", p.x, p.y,
                                    [w.id, v.id], True))
                continue
            points = [inter] if inter.geom_type == "Point" else [
                g for g in getattr(inter, "geoms", []) if g.geom_type == "Point"]
            for p in points:
                at_shared = any(Point(plan.nodes[n]).distance(p) <= NODE_TOL for n in shared)
                if at_shared:
                    continue
                # конец одной стены на другой стене — примыкание без узла, разрезается само
                ends = [n for n in (w.a, w.b, v.a, v.b)
                        if Point(plan.nodes[n]).distance(p) <= NODE_TOL]
                if ends:
                    issues.append(Issue("t_joint", "Стена примыкает не в узле", p.x, p.y,
                                        [w.id, v.id], True))
                else:
                    issues.append(Issue("crossing", "Стены пересекаются не в узле", p.x, p.y,
                                        [w.id, v.id], False))

    by_wall: dict[str, list[Opening]] = {}
    for op in plan.openings:
        wall = walls.get(op.wall)
        if wall is None or wall.a not in plan.nodes or wall.b not in plan.nodes:
            issues.append(Issue("orphan_opening", "Проём не в стене", 0, 0, [op.id], True))
            continue
        line = centerline(plan, wall)
        start, end = _opening_span(plan, op)
        p = line.interpolate(max(0, min(op.at, line.length)))
        if start < -0.5 or end > line.length + 0.5:
            issues.append(Issue("opening_outside", "Проём за гранью стены", p.x, p.y,
                                [op.id], True))
        by_wall.setdefault(op.wall, []).append(op)
    for ops in by_wall.values():
        ops.sort(key=lambda o: o.at)
        for prev, cur in zip(ops, ops[1:], strict=False):
            if _opening_span(plan, cur)[0] < _opening_span(plan, prev)[1] - 0.5:
                line = centerline(plan, walls[cur.wall])
                p = line.interpolate(max(0, min(cur.at, line.length)))
                issues.append(Issue("openings_overlap", "Проёмы друг на друге", p.x, p.y,
                                    [prev.id, cur.id], True))

    if rooms is not None:
        placed = {label for room in rooms for label in room.labels}
        for label in plan.rooms:
            if label.id not in placed:
                title = " ".join(p for p in (label.number, label.name) if p) or "без номера"
                issues.append(Issue("label_outside", f"Подпись помещения «{title}» вне "
                                    "помещений", label.x, label.y, [label.id], False))
        for room in rooms:
            if len(room.labels) > 1:
                x, y = room.anchor()
                issues.append(Issue("labels_together", "В одном помещении несколько подписей",
                                    x, y, list(room.labels), False))
    return issues


# ---------------------------------------------------------------- исправление

def fix(plan: Plan) -> tuple[Plan, list[str]]:
    """Исправить то, что исправляется однозначно (5.1.5); вернуть новый план и что сделано.
    Пересечения стен не в узле остаются — их правят вручную."""
    plan = plan.model_copy(deep=True)
    done: dict[str, int] = {}

    def note(what: str, n: int = 1) -> None:
        if n:
            done[what] = done.get(what, 0) + n

    # стены без узлов и проёмы без стен
    before = len(plan.walls)
    plan.walls = [w for w in plan.walls if w.a in plan.nodes and w.b in plan.nodes]
    note("убраны стены без узлов", before - len(plan.walls))

    # близкие узлы — один узел; короткие стены схлопываются
    _merge_close_nodes(plan, note)
    before = len(plan.walls)
    plan.walls = [w for w in plan.walls if w.a != w.b]
    note(f"убраны стены короче {MIN_WALL:.0f} мм", before - len(plan.walls))

    # двойные стены
    keep: dict[tuple[str, ...], Wall] = {}
    removed: dict[str, str] = {}
    for w in plan.walls:
        if abs(w.bulge) > 1e-9:
            keep[(w.id,)] = w
            continue
        key = tuple(sorted((w.a, w.b)))
        other = keep.get(key)
        if other is None:
            keep[key] = w
        else:
            better = max(other, w, key=lambda x: (x.kind == "bearing", x.thickness))
            worse = w if better is other else other
            keep[key] = better
            removed[worse.id] = better.id
    if removed:
        plan.walls = list(keep.values())
        for op in plan.openings:
            if op.wall in removed:
                op.wall = removed[op.wall]
        note("убраны двойные стены", len(removed))

    # примыкания не в узле — разрезать стену в точке примыкания
    note("стены разрезаны в местах примыкания", _split_t_joints(plan))

    # проёмы
    walls = {w.id: w for w in plan.walls}
    before = len(plan.openings)
    plan.openings = [op for op in plan.openings if op.wall in walls]
    note("убраны проёмы без стен", before - len(plan.openings))
    moved = 0
    by_wall: dict[str, list[Opening]] = {}
    for op in plan.openings:
        by_wall.setdefault(op.wall, []).append(op)
    for wall_id, ops in by_wall.items():
        length = wall_length(plan, walls[wall_id])
        ops.sort(key=lambda o: o.at)
        cursor = 0.0
        for op in ops:
            if op.width > length:
                op.width = length
                moved += 1
            lo = max(cursor + op.width / 2, op.width / 2)
            hi = length - op.width / 2
            target = min(max(op.at, lo), hi)
            if abs(target - op.at) > 0.01:
                op.at = target
                moved += 1
            cursor = op.at + op.width / 2
    note("проёмы сдвинуты в пределы стены и друг с друга", moved)
    return plan, [f"{what}: {n}" for what, n in done.items()]


def _merge_close_nodes(plan: Plan, note: object) -> None:
    ids = list(plan.nodes)
    alias: dict[str, str] = {}
    points = [Point(plan.nodes[i]) for i in ids]
    tree = STRtree(points)
    for k, nid in enumerate(ids):
        if nid in alias:
            continue
        for j in tree.query(points[k].buffer(NODE_TOL)):
            other = ids[int(j)]
            if other != nid and other not in alias and points[k].distance(points[int(j)]) \
                    < NODE_TOL:
                alias[other] = nid
    if not alias:
        return
    for w in plan.walls:
        w.a = alias.get(w.a, w.a)
        w.b = alias.get(w.b, w.b)
    for other in alias:
        plan.nodes.pop(other, None)
    note("объединены близкие узлы", len(alias))  # type: ignore[operator]


def _split_t_joints(plan: Plan) -> int:
    count = 0
    changed = True
    while changed:
        changed = False
        degree: dict[str, int] = {}
        for w in plan.walls:
            degree[w.a] = degree.get(w.a, 0) + 1
            degree[w.b] = degree.get(w.b, 0) + 1
        for w in list(plan.walls):
            if abs(w.bulge) > 1e-9:
                continue
            line = centerline(plan, w)
            for nid, xy in plan.nodes.items():
                if nid in (w.a, w.b) or nid not in degree:
                    continue
                p = Point(xy)
                if line.distance(p) > ON_LINE:
                    continue
                at = line.project(p)
                if at < NODE_TOL or at > line.length - NODE_TOL:
                    continue
                _split_wall(plan, w, nid, at)
                count += 1
                changed = True
                break
            if changed:
                break
    return count


def _split_wall(plan: Plan, wall: Wall, node: str, at: float) -> Wall:
    """Разрезать прямую стену в узле node, лежащем на ней в at мм от начала."""
    new = wall.model_copy(update={"id": f"{wall.id}-{node}", "a": node})
    wall.b = node
    plan.walls.append(new)
    for op in plan.openings:
        if op.wall == wall.id and op.at > at:
            op.wall = new.id
            op.at -= at
    return new
