"""Разбиение чертежа на части: на одном листе модели обычно лежат планы нескольких
этажей рядом. Часть — связная группа фигур здания; между частями — пустое поле."""

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from app.modules.building.drawing.layers import FLOOR, role
from app.modules.building.drawing.read import Drawing, Seg

CELL = 1000.0  # мм: шаг сетки, по которой ищутся связные группы
GAP = 3  # клеток пустоты, которые ещё не разделяют части
MIN_SEGS = 10  # меньше фигур здания — не этаж (одинокий знак)
STRUCTURE = {"wall", "partition", "window", "door", "column", "stair", "lift", "fill", "other"}


@dataclass
class Part:
    key: str
    bbox: tuple[float, float, float, float]
    segs: int
    name: str = ""  # «План 3-го этажа», найденное на чертеже
    level: int | None = None  # номер этажа из названия
    preview: str = ""  # SVG-путь в квадрате 0..1000
    extra: dict[str, object] = field(default_factory=dict)


def _cells(s: Seg) -> list[tuple[int, int]]:
    length = math.dist(s.a, s.b)
    n = max(1, int(length / (CELL / 2)))
    out = []
    for i in range(n + 1):
        x = s.a[0] + (s.b[0] - s.a[0]) * i / n
        y = s.a[1] + (s.b[1] - s.a[1]) * i / n
        out.append((int(math.floor(x / CELL)), int(math.floor(y / CELL))))
    return out


def split(drawing: Drawing) -> list[Part]:
    segs = [s for s in drawing.segs if role(s.layer) in STRUCTURE and math.dist(s.a, s.b) < 200_000]
    occupied: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, s in enumerate(segs):
        for c in set(_cells(s)):
            occupied[c].append(i)
    # связные группы клеток с допуском GAP
    label: dict[tuple[int, int], int] = {}
    groups = 0
    for start in occupied:
        if start in label:
            continue
        stack = [start]
        label[start] = groups
        while stack:
            cx, cy = stack.pop()
            for dx in range(-GAP, GAP + 1):
                for dy in range(-GAP, GAP + 1):
                    c = (cx + dx, cy + dy)
                    if c in occupied and c not in label:
                        label[c] = groups
                        stack.append(c)
        groups += 1
    members: dict[int, set[int]] = defaultdict(set)
    for c, idx in occupied.items():
        members[label[c]].update(idx)
    parts: list[Part] = []
    for g, idx in members.items():
        if len(idx) < MIN_SEGS:
            continue
        xs = [p[0] for i in idx for p in (segs[i].a, segs[i].b)]
        ys = [p[1] for i in idx for p in (segs[i].a, segs[i].b)]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        part = Part(key=f"p{g}", bbox=bbox, segs=len(idx))
        part.preview = _preview([segs[i] for i in idx], bbox)
        parts.append(part)
    # слева направо, сверху вниз — как обычно раскладывают этажи на листе
    parts.sort(key=lambda p: (round(-p.bbox[3] / 20000), p.bbox[0]))
    for i, part in enumerate(parts, 1):
        part.key = f"p{i}"
    _names(drawing, parts)
    return parts


def _names(drawing: Drawing, parts: list[Part]) -> None:
    for part in parts:
        x0, y0, x1, y1 = part.bbox
        w, h = x1 - x0, y1 - y0
        best: tuple[float, str] | None = None
        for t in drawing.texts:
            if not FLOOR.search(t.text) or len(t.text) > 60:
                continue
            # название — внутри части или над ней, в пределах её ширины
            if not (x0 - 0.1 * w <= t.x <= x1 + 0.1 * w and y0 - 0.15 * h <= t.y <= y1 + 0.35 * h):
                continue
            score = t.height * (2 if "план" in t.text.lower() else 1)
            if best is None or score > best[0]:
                best = (score, t.text.strip())
        if best:
            part.name = re.sub(r"\s+", " ", best[1])
            m = re.search(r"(-?\d+)\s*-?\s*(го|й|ой|ий)?\s*этаж", part.name, re.IGNORECASE)
            if m:
                part.level = int(m.group(1))
            elif re.search(r"подвал|цокол", part.name, re.IGNORECASE):
                part.level = -1
            # план кровли — не этаж: на нём нет помещений, и этажом он не становится
            if re.search(r"кровл|крыш", part.name, re.IGNORECASE):
                part.extra["roof"] = True


def _preview(segs: list[Seg], bbox: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = bbox
    k = 1000 / max(x1 - x0, y1 - y0, 1)
    seen = set()
    out = []
    for s in sorted(segs, key=lambda s: -math.dist(s.a, s.b))[:4000]:
        a = (round((s.a[0] - x0) * k), round((y1 - s.a[1]) * k))
        b = (round((s.b[0] - x0) * k), round((y1 - s.b[1]) * k))
        if a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        out.append(f"M{a[0]} {a[1]}L{b[0]} {b[1]}")
    return "".join(out)
