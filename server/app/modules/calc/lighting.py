"""Освещённость (5.3.5, С8).

Каждое помещение считается отдельно — свет через стены и двери не проходит: сетка точек на
рабочей поверхности (высота — из назначения помещения: 0,8 м для кабинета, пол для
коридора), от каждого светильника этого помещения прямой свет E = I(γ)·cos θ / d². Сила
света I(γ) — по световому потоку и типу кривой силы света: I = I₀·cosⁿγ, где n по типу
кривой (Г — глубокая 3, Д — косинусная 1, Л — полуширокая 0,5, Ш — широкая 0,25,
М — равномерная 0), а I₀ такая, чтобы в нижнюю полусферу уходил весь поток. Отражения от
стен и потолка — прибавкой-коэффициентом, итог делится на коэффициент запаса (настройки,
4.6). Помещение сравнивается с нормой его назначения по средней освещённости; точки ниже
нормы подсвечены.
"""

import math
from typing import Any

import numpy as np
import shapely
from shapely.geometry import Polygon

from app.modules.calc.api import Calculation, Ctx, Param, Result, register
from app.modules.calc.cameras import _number
from app.modules.catalog import api as catalog
from app.modules.system import api as system

KEY = "light"
FLUX = "Световой поток"
CURVE = "Тип кривой силы света"
POWER = {"Г": 3.0, "Д": 1.0, "Л": 0.5, "Ш": 0.25, "М": 0.0}
MAX_POINTS = 60_000

# раскраска в люксах
SCALE = [
    [0, "#2C3E91"],
    [50, "#3B6FB6"],
    [100, "#4FA3C7"],
    [200, "#8BCF9B"],
    [300, "#E8E36B"],
    [500, "#F5A742"],
    [750, "#E8613A"],
    [1000, "#C62828"],
]

SETTINGS = {
    "calc_light_maintenance": system.SettingDef(
        "Освещённость: коэффициент запаса", 1.4, _number(1, 3, "Коэффициент запаса")
    ),
    "calc_light_reflection": system.SettingDef(
        "Освещённость: прибавка за отражения, доля", 0.2, _number(0, 1, "Прибавка за отражения")
    ),
    "calc_light_step_mm": system.SettingDef(
        "Освещённость: шаг сетки, мм", 250, _number(50, 2000, "Шаг сетки")
    ),
}


def _power(value: Any) -> float:
    text = str(value or "").strip()
    return POWER.get(text[:1].upper(), 1.0)


def _illuminance(points: np.ndarray, height: float, lights: list[dict[str, float]]) -> np.ndarray:
    """Прямая освещённость в точках (x, y) на высоте height, лк (размеры — мм)."""
    total = np.zeros(len(points))
    for lt in lights:
        dz = lt["z"] - height
        if dz <= 0:
            continue
        v = np.column_stack(
            [points[:, 0] - lt["x"], points[:, 1] - lt["y"], np.full(len(points), -dz)]
        )
        d = np.linalg.norm(v, axis=1) / 1000  # м
        unit = v / (d[:, None] * 1000)
        cos_g = unit @ lt["axis"]  # угол от оси светильника
        n = lt["n"]
        i0 = lt["flux"] * (n + 1) / (2 * math.pi)
        intensity = np.where(cos_g > 0, i0 * np.power(np.clip(cos_g, 0, 1), n), 0.0)
        cos_t = dz / (d * 1000)  # падение на горизонтальную поверхность
        total += intensity * cos_t / (d * d)
    return total


def compute(ctx: Ctx, options: dict[str, str]) -> Result:
    keep = float(ctx.setting("calc_light_maintenance"))
    extra = float(ctx.setting("calc_light_reflection"))
    step0 = float(ctx.setting("calc_light_step_mm"))
    purposes = catalog.purpose_map(ctx.session)
    r = Result()
    r.legend = [{"color": c, "title": f"{v} лк"} for v, c in SCALE] + [
        {"color": "#D32F2F", "title": "ниже нормы", "hatch": True}
    ]
    by_room: dict[Any, list[dict[str, float]]] = {}
    for t in ctx.things:
        if t.room_id is None:
            r.missing.append(
                {
                    "item_id": t.id,
                    "x": t.x,
                    "y": t.y,
                    "text": f"{t.name}: вне помещений — не считается",
                }
            )
            continue
        tilt = math.radians(t.param(KEY, "tilt", 0))
        a = math.radians(t.angle)
        # ось — вниз, наклон — к передней стороне светильника (+Y предмета)
        front = np.array([-math.sin(a), math.cos(a), 0.0])
        axis = np.array([0.0, 0.0, -math.cos(tilt)]) + front * math.sin(tilt)
        z = t.z + (t.type.height or 0) if t.type.mount == "floor" else t.z
        by_room.setdefault(t.room_id, []).append(
            {
                "x": t.x,
                "y": t.y,
                "z": z,
                "flux": t.number(FLUX) or 0,
                "n": _power(t.values.get(CURVE)),
                "axis": axis,
            }
        )
        if t.note:
            r.missing.append({"item_id": t.id, "x": t.x, "y": t.y, "text": f"{t.name}: {t.note}"})
    rooms = [x for x in ctx.rooms if x.id in by_room or purposes.get(x.purpose_id or "")]
    area = sum(Polygon(x.outline).area for x in rooms)
    step = max(step0, math.sqrt(area / MAX_POINTS) if area else step0)
    rows, low, table = [], [], []
    cells_all: list[list[float]] = []
    below_all: list[list[float]] = []
    for room in rooms:
        purpose = purposes.get(room.purpose_id or "")
        surface = float(purpose.surface) if purpose else 800.0
        norm = int(purpose.norm) if purpose else None
        lights = by_room.get(room.id, [])
        shape = Polygon(room.outline).buffer(0)
        x0, y0, x1, y1 = shape.bounds
        xs = np.arange(x0 + step / 2, x1, step)
        ys = np.arange(y0 + step / 2, y1, step)
        if not len(xs) or not len(ys):
            continue
        gx, gy = np.meshgrid(xs, ys)
        inside = shapely.contains_xy(shape, gx.ravel(), gy.ravel())
        pts = np.column_stack([gx.ravel()[inside], gy.ravel()[inside]])
        if not len(pts):
            pts = np.array([[room.x, room.y]])
        e = _illuminance(pts, surface, lights) * (1 + extra) / keep
        avg, low_e = float(e.mean()), float(e.min())
        uniform = low_e / avg if avg > 0 else 0.0
        cells_all += [[round(x), round(y), round(v)] for (x, y), v in zip(pts, e, strict=True)]
        if norm:
            below_all += [
                [round(x), round(y)] for (x, y), v in zip(pts, e, strict=True) if v < norm
            ]
        name = " ".join(x for x in (room.number, room.name) if x) or "помещение без номера"
        bad = norm is not None and avg < norm
        r.draw.append(
            {
                "kind": "label",
                "x": room.x,
                "y": room.y,
                "text": f"ср. {avg:.0f} · мин {low_e:.0f} лк"
                + (f" / норма {norm}" if norm else " / норма не задана"),
                "short": f"{avg:.0f}" + (f" / {norm}" if norm else "") + " лк",
                "width": x1 - x0,
                "tone": "bad" if bad else "ok" if norm else "muted",
            }
        )
        table.append(
            [
                name,
                purpose.name if purpose else "—",
                f"{surface / 1000:.1f}",
                str(norm) if norm else "—",
                f"{avg:.0f}",
                f"{low_e:.0f}",
                f"{uniform:.2f}",
                str(len(lights)),
            ]
        )
        rows.append(room.id)
        if bad:
            low.append(
                {
                    "text": f"{name}: ср. {avg:.0f} лк при норме {norm}"
                    + ("" if lights else " — светильников нет"),
                    "x": room.x,
                    "y": room.y,
                    "room_id": str(room.id),
                }
            )
    r.draw.insert(
        0,
        {"kind": "cells", "size": round(step), "cells": cells_all, "scale": SCALE, "opacity": 0.55},
    )
    if below_all:
        r.draw.insert(
            1,
            {
                "kind": "cells",
                "size": round(step),
                "cells": below_all,
                "color": "#D32F2F",
                "hatch": True,
            },
        )
    r.table = {
        "title": "Помещения",
        "columns": [
            "Помещение",
            "Назначение",
            "Поверхность, м",
            "Норма, лк",
            "Средняя, лк",
            "Мин., лк",
            "Равномерность",
            "Светильников",
        ],
        "rows": table,
        "room_ids": [str(x) for x in rows],
    }
    with_norm = sum(1 for x in rooms if purposes.get(x.purpose_id or ""))
    r.summary.append(
        f"Помещений ниже нормы: {len(low)} из {with_norm} с назначением. Коэффициент запаса "
        f"{keep:g}, отражения +{extra:.0%}, шаг сетки {step / 1000:.2f} м."
    )
    if len(rooms) > with_norm:
        r.summary.append(
            f"Без назначения: {len(rooms) - with_norm} — норма не известна; назначение задаётся "
            "у помещения в «Строительстве»."
        )
    r.issues = {"title": "Ниже нормы", "rows": low}
    return r


register(
    Calculation(
        key=KEY,
        title="Освещённость",
        about="Освещённость рабочей поверхности каждого помещения в люксах и сравнение с нормой.",
        needs=[FLUX, CURVE],
        params=[Param("tilt", "Наклон", "°", 0, 90, "К передней стороне светильника")],
        options=[],
        compute=compute,
        settings=SETTINGS,
    )
)
