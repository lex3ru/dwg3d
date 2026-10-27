"""Обзор камер (5.3.4, С7).

Зона обзора — на высоте лица (1,6 м, настраивается): сектор угла обзора камеры между
ближней и дальней границей, которые дают высота, наклон и угол по вертикали; стены и
колонны закрывают обзор (лучи из камеры до первого препятствия). Зона делится по плотности
изображения на уровни DORI (4.6; IEC 62676-4:2014 / EN 62676-4:2015 — ГОСТ Р 51558-2014 таких
уровней не задаёт, 11.1 п. 2): обнаружение ≥ 25 пк/м, наблюдение ≥ 62,5, узнавание ≥ 125,
идентификация ≥ 250; пороги — настройки. Плотность на расстоянии D:
разрешение по горизонтали / ширина кадра 2·D·tg(угол/2); у широкоугольных (от 120°) —
разрешение / (угол в радианах · D).
"""

import math
from typing import Any

import numpy as np
from shapely import STRtree
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from app.modules.calc.api import Calculation, Ctx, Option, Param, Result, register, rings
from app.modules.system import api as system

KEY = "camera"
H_RES = "Разрешение по горизонтали"
V_RES = "Разрешение по вертикали"
H_MIN = "Угол обзора по горизонтали, мин."
H_MAX = "Угол обзора по горизонтали, макс."
V_ANGLE = "Угол обзора по вертикали"

# от широкого к узкому: рисуются в этом порядке, узкие — поверх
LEVELS = [
    ("detect", "обнаружение", "calc_px_detect", 25, "#64B5F6"),
    ("observe", "наблюдение", "calc_px_observe", 62.5, "#81C784"),
    ("recognize", "узнавание", "calc_px_recognize", 125, "#FFD54F"),
    ("identify", "идентификация", "calc_px_identify", 250, "#E57373"),
]
STEP = 0.5  # градусов между лучами


def _number(low: float, high: float, what: str) -> Any:
    def check(value: Any) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{what}: нужно число.") from None
        if not low <= v <= high:
            raise ValueError(f"{what}: от {low:g} до {high:g}.")
        return v

    return check


SETTINGS = {
    "calc_face_height_mm": system.SettingDef(
        "Камеры: высота лица, мм", 1600, _number(0, 3000, "Высота лица")
    ),
    "calc_camera_range_m": system.SettingDef(
        "Камеры: предельная дальность, м", 60, _number(5, 500, "Дальность")
    ),
    **{
        key: system.SettingDef(f"Камеры: {title}, пк/м", default, _number(1, 5000, title))
        for _, title, key, default, _ in LEVELS
    },
}


class Scene:
    """Препятствия этажа с деревом поиска и отрезками границ — строятся раз на версию плана."""

    def __init__(self, obstacles: list[Any]):
        self.obstacles = obstacles
        self.tree = STRtree(obstacles)
        self.edges: list[tuple[np.ndarray, np.ndarray]] = []
        for g in obstacles:
            polys = [g] if isinstance(g, Polygon) else list(getattr(g, "geoms", []))
            a, b = [], []
            for p in polys:
                if not isinstance(p, Polygon):
                    continue
                for ring in [p.exterior, *p.interiors]:
                    c = np.asarray(ring.coords)
                    a.append(c[:-1])
                    b.append(c[1:])
            self.edges.append(
                (np.concatenate(a), np.concatenate(b))
                if a
                else (np.zeros((0, 2)), np.zeros((0, 2)))
            )

    def segments(self, centre: Point, reach: float) -> tuple[np.ndarray, np.ndarray]:
        """Отрезки границ препятствий в пределах досягаемости. Препятствие, в котором стоит
        сама камера (камера на стене), не мешает."""
        found = [
            self.edges[int(i)]
            for i in self.tree.query(centre.buffer(reach, quad_segs=4))
            if not self.obstacles[int(i)].contains(centre)
        ]
        if not found:
            return np.zeros((0, 2)), np.zeros((0, 2))
        return np.concatenate([a for a, _ in found]), np.concatenate([b for _, b in found])


_scenes: dict[tuple[Any, int], Scene] = {}
# зоны камер по всему, от чего они зависят: тащат одну камеру — остальные из памяти (8.2)
_zones: dict[
    tuple[Any, ...], tuple[dict[str, Polygon], dict[str, float], float, dict[str, Any]]
] = {}


def _frozen(value: Any) -> Any:
    """Списки — в кортежи: кортежи из чисел сборка мусора не отслеживает, и кэш зон не удлиняет
    каждую полную сборку (8.2, DWG3D-10, ADR-0010)."""
    if isinstance(value, list):
        return tuple(_frozen(v) for v in value)
    if isinstance(value, dict):
        return {k: _frozen(v) for k, v in value.items()}
    return value


def _scene(ctx: Ctx) -> Scene:
    key = (ctx.floor.id, ctx.floor.plan_version)
    if key not in _scenes:
        if len(_scenes) > 16:
            _scenes.clear()
        _scenes[key] = Scene(ctx.obstacles)
    return _scenes[key]


def _hits(p: np.ndarray, dirs: np.ndarray, a: np.ndarray, b: np.ndarray, far: float) -> np.ndarray:
    """Расстояние по каждому лучу до первого препятствия (или far)."""
    if not len(a):
        return np.full(len(dirs), far)
    e = b - a  # (M, 2)
    ap = a - p  # (M, 2)
    dx, dy = dirs[:, 0:1], dirs[:, 1:2]  # (N, 1)
    denom = dx * e[:, 1] - dy * e[:, 0]  # (N, M)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (ap[:, 0] * e[:, 1] - ap[:, 1] * e[:, 0]) / denom
        u = (ap[:, 0] * dy - ap[:, 1] * dx) / denom
    ok = (np.abs(denom) > 1e-9) & (t > 1e-6) & (u >= 0) & (u <= 1)
    t = np.where(ok, t, far)
    return np.minimum(t.min(axis=1), far)


class Camera:
    def __init__(self, ctx: Ctx, thing: Any, face: float, limit: float):
        self.thing = thing
        t = thing.type
        # объектив: на стене и потолке — у низа корпуса, напольная — сверху
        self.z = thing.z + (t.height or 0) if t.mount == "floor" else thing.z
        lo = thing.number(H_MIN) or thing.number(H_MAX) or 90
        hi = thing.number(H_MAX) or lo
        self.fov = min(max(thing.param(KEY, "fov", hi), min(lo, hi)), max(lo, hi))
        self.res = thing.number(H_RES) or 1920
        v_angle = thing.number(V_ANGLE)
        v_res = thing.number(V_RES)
        if v_angle:
            self.vfov = v_angle
        elif v_res and self.fov < 170:
            self.vfov = math.degrees(
                2 * math.atan(math.tan(math.radians(self.fov / 2)) * v_res / self.res)
            )
        else:
            self.vfov = self.fov * 9 / 16
        self.fisheye = self.fov >= 170
        default_tilt = 90 if self.fisheye else (35 if t.mount == "ceiling" else 15)
        self.tilt = min(max(thing.param(KEY, "tilt", default_tilt), -30), 90)
        self.heading = thing.angle + 90  # передняя сторона предмета — его +Y
        dz = self.z - face
        self.dz = dz
        if self.fisheye:
            self.near, self.far = 0.0, limit
        else:
            lower = self.tilt + self.vfov / 2
            upper = self.tilt - self.vfov / 2
            self.near = dz / math.tan(math.radians(lower)) if dz > 0 and lower < 89.9 else 0.0
            self.far = dz / math.tan(math.radians(upper)) if dz > 0 and upper > 0.1 else limit
            self.far = min(self.far, limit)

    def reach(self, ppm: float) -> float:
        """Горизонтальная дальность уровня с плотностью ppm (мм)."""
        f = math.radians(self.fov)
        slant = (
            self.res / (f * ppm) if self.fov >= 120 else self.res / (2 * math.tan(f / 2) * ppm)
        ) * 1000
        return math.sqrt(slant * slant - self.dz * self.dz) if slant > abs(self.dz) else 0.0


def _zone(cam: Camera, angles: np.ndarray, hits: np.ndarray, radius: float) -> Polygon:
    p = np.array([cam.thing.x, cam.thing.y])
    outer = np.minimum(np.minimum(hits, cam.far), radius)
    near = cam.near
    if radius <= near or not (outer > near).any():
        return Polygon()
    outer = np.maximum(outer, near)
    dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    ring = p + dirs * outer[:, None]
    if cam.fisheye:
        shape = Polygon(ring)
    else:
        inner = (p + dirs * near)[::-1] if near > 1 else p[None, :]
        shape = Polygon(np.concatenate([ring, inner]))
    return shape if shape.is_valid else shape.buffer(0)


def compute(ctx: Ctx, options: dict[str, str]) -> Result:
    face = float(ctx.setting("calc_face_height_mm"))
    limit = float(ctx.setting("calc_camera_range_m")) * 1000
    levels = [(k, title, float(ctx.setting(s)), color) for k, title, s, _, color in LEVELS]
    r = Result()
    r.legend = [{"color": c, "title": f"{t} ≥ {ppm:g} пк/м"} for _, t, ppm, c in levels]
    coverage: dict[str, list[Polygon]] = {k: [] for k, *_ in levels}
    rows = []
    scene = _scene(ctx)
    for thing in ctx.things:
        cam = Camera(ctx, thing, face, limit)
        key = (
            ctx.floor.id,
            ctx.floor.plan_version,
            thing.type.id,
            thing.model.id if thing.model else None,
            thing.x,
            thing.y,
            thing.z,
            thing.angle,
            tuple(sorted(thing.params.items())),
            face,
            limit,
            tuple(ppm for _, _, ppm, _ in levels),
        )
        if key not in _zones:
            if len(_zones) > 5000:
                _zones.clear()
            radii = {k: min(cam.reach(ppm), limit) for k, _, ppm, _ in levels}
            reach = max(min(max(radii.values()), cam.far), 1)
            span = 360.0 if cam.fisheye else cam.fov
            start = math.radians(cam.heading - span / 2)
            n = max(2, int(span / STEP) + 1)
            angles = start + np.radians(np.linspace(0, span, n, endpoint=not cam.fisheye))
            dirs = np.stack([np.cos(angles), np.sin(angles)], axis=1)
            a, b = scene.segments(Point(thing.x, thing.y), reach + 10)
            hits = _hits(np.array([thing.x, thing.y]), dirs, a, b, reach + 10)
            shapes = {k: _zone(cam, angles, hits, radii[k]) for k, *_ in levels}
            drawn = {k: rings(z.simplify(5)) for k, z in shapes.items()}
            cone3d = _cone(cam, shapes, angles, hits, radii[LEVELS[0][0]])
            _zones[key] = (shapes, _frozen(drawn), radii, reach, _frozen(cone3d))
        shapes, drawn, radii, reach, cone = _zones[key]
        for k, _, _, color in levels:
            zone = shapes[k]
            if zone.is_empty:
                continue
            coverage[k].append(zone)
            r.draw.append(
                {
                    "kind": "polygon",
                    "rings": drawn[k],
                    "fill": color,
                    "opacity": 0.28,
                    "item_id": thing.id,
                }
            )
        r.draw3d += [{**c, "item_id": thing.id} for c in cone]
        rows.append(
            [
                thing.type.name + (f" «{thing.label}»" if thing.label else ""),
                f"{thing.model.manufacturer} {thing.model.name}" if thing.model else "—",
                f"{cam.z / 1000:.1f}",
                f"{(thing.angle % 360):.0f}°",
                "—" if cam.fisheye else f"{cam.tilt:.0f}°",
                f"{cam.fov:.0f}°",
                *[f"{min(radii[k], cam.far) / 1000:.1f}" for k, *_ in reversed(levels)],
            ]
        )
    r.table = {
        "title": "Камеры этажа",
        "columns": [
            "Камера",
            "Модель",
            "Высота, м",
            "Поворот",
            "Наклон",
            "Угол",
            *[f"{t}, м" for _, t, _, _ in reversed(levels)],
        ],
        "rows": rows,
        "item_ids": [t.id for t in ctx.things],
    }
    r.summary.append(
        f"Камер: {len(ctx.things)}. Зоны — на высоте {face / 1000:.1f} м; стены и колонны "
        "закрывают обзор."
    )
    unseen = options.get("unseen", "off")
    if unseen != "off" and ctx.rooms:
        _unseen(ctx, r, options, coverage, unseen, dict((k, t) for k, t, *_ in levels))
    for thing in ctx.things:
        if thing.note:
            r.missing.append(
                {
                    "item_id": thing.id,
                    "x": thing.x,
                    "y": thing.y,
                    "text": f"{thing.type.name}: {thing.note}",
                }
            )
    return r


def _unseen(
    ctx: Ctx,
    r: Result,
    options: dict[str, str],
    coverage: dict[str, list[Polygon]],
    level: str,
    titles: dict[str, str],
) -> None:
    """«Непросматриваемые места» (5.3.4 п. 4): части помещений, куда не достаёт ни одна
    камера на выбранном уровне."""
    order = [k for k, *_ in LEVELS]
    # уровень «узнавание» покрывает и то, что видно на «идентификации»
    seen = (
        unary_union([z for k in order[order.index(level) :] for z in coverage[k]])
        if any(coverage.values())
        else Polygon()
    )
    rooms = [x for x in ctx.rooms if str(x.id) == options.get("room")] or ctx.rooms
    total = lost = 0.0
    rows = []
    for room in rooms:
        shape = Polygon(room.outline).buffer(0)
        gap = shape.difference(seen) if not seen.is_empty else shape
        gap = unary_union([g for g in getattr(gap, "geoms", [gap]) if g.area >= 50_000])
        total += shape.area
        if gap.is_empty:
            continue
        lost += gap.area
        r.draw.append(
            {
                "kind": "polygon",
                "rings": rings(gap),
                "fill": "#D32F2F",
                "opacity": 0.25,
                "hatch": True,
            }
        )
        at = max(getattr(gap, "geoms", [gap]), key=lambda g: g.area).representative_point()
        name = " ".join(x for x in (room.number, room.name) if x) or "помещение без номера"
        rows.append(
            {
                "text": f"{name}: {gap.area / 1e6:.1f} м² ({gap.area / shape.area:.0%})",
                "x": round(at.x),
                "y": round(at.y),
                "room_id": str(room.id),
                "area": gap.area,
            }
        )
    rows.sort(key=lambda x: -x["area"])
    for row in rows:
        del row["area"]
    r.legend.append(
        {"color": "#D32F2F", "title": f"не просматривается ({titles[level]})", "hatch": True}
    )
    where = "в помещении" if len(rooms) == 1 else "на этаже"
    r.summary.append(
        f"Не просматривается ({titles[level]}) {where}: {lost / 1e6:.1f} м² из "
        f"{total / 1e6:.1f} м² ({(lost / total if total else 0):.0%})."
    )
    r.issues = {"title": f"Не просматривается — {titles[level]}", "rows": rows[:50]}


FLOOR3D = 20.0  # мм над полом: пятна зон в 3D лежат на полу, как в прежней версии


def _cone(
    cam: Camera, shapes: dict[str, Polygon], angles: np.ndarray, hits: np.ndarray, radius: float
) -> list[dict[str, Any]]:
    """Зона в 3D (5.3.4 п. 2), как в прежней версии: пятна уровней на полу, полупрозрачный
    конус из объектива до дальнего края зоны, его боковые рёбра и линия по краю. Край — те же
    лучи, что на плане, поэтому стены обрезают и конус."""
    t = cam.thing
    out: list[dict[str, Any]] = []
    for k, _, _, _, color in LEVELS:
        zone = shapes.get(k)
        if zone is not None and not zone.is_empty:
            out.append(
                {
                    "kind": "polygon3d",
                    "rings": rings(zone.simplify(20)),
                    "z": FLOOR3D,
                    "color": color,
                    "opacity": 0.22,
                }
            )
    reach = np.minimum(np.minimum(hits, cam.far), radius)
    if not (reach > 1).any():
        return out
    p = np.array([t.x, t.y])
    arc = p + np.stack([np.cos(angles), np.sin(angles)], axis=1) * reach[:, None]
    arc = np.round(arc[:: max(1, len(arc) // 120)]).tolist()
    apex = [round(t.x), round(t.y), round(cam.z)]
    out.append(
        {
            "kind": "fan",
            "apex": apex,
            "arc": arc,
            "z": FLOOR3D,
            "closed": cam.fisheye,
            "color": "#1E88E5",
            "opacity": 0.08,
        }
    )
    rim = [[x, y, FLOOR3D + 5] for x, y in arc]
    segs = [[rim[i], rim[i + 1]] for i in range(len(rim) - 1)]
    if cam.fisheye:
        segs.append([rim[-1], rim[0]])
    else:
        segs += [[apex, rim[0]], [apex, rim[-1]]]
    out.append({"kind": "lines", "color": "#1E88E5", "segments": segs})
    return out


register(
    Calculation(
        key=KEY,
        title="Обзор камер",
        about="Зона обзора на высоте лица по уровням различимости; стены закрывают обзор.",
        needs=[H_RES, H_MAX],
        params=[
            Param("tilt", "Наклон вниз", "°", -30, 90, "От горизонта; потолочная — до 90°"),
            Param("fov", "Угол обзора", "°", 1, 360, "У вариофокальной — в пределах модели"),
        ],
        options=[
            Option(
                "unseen",
                "Непросматриваемые места",
                [("off", "не показывать"), *[(k, t) for k, t, *_ in LEVELS]],
                "off",
            )
        ],
        compute=compute,
        settings=SETTINGS,
    )
)
