"""Подписи, нарисованные линиями: на некоторых чертежах текст разбит на отрезки (шрифт
превращён в линии), и номер помещения — это несколько маленьких ломаных. Они читаются
сравнением с образцами цифр чертёжного шрифта (наклонный, как ГОСТ 2.304 / ISOCPEUR):
каждый знак приводится к высоте 1, обходится точками и сравнивается с образцами по
среднему расстоянию между точками."""

import math
from dataclasses import dataclass

from app.modules.building.drawing.read import Seg

# образцы: ломаные в долях высоты знака, от левого нижнего угла рамки знака
TEMPLATES: dict[str, list[str]] = {
    "1": ["0,0.743 0.314,1 0.057,0"],
    "2": ["0.444,0 0,0 0.611,0.667 0.667,0.806 0.611,0.944 0.5,1 0.361,0.972 0.25,0.861"],
    "3": [
        "0.371,0.543 0.514,0.6 0.629,0.714 0.657,0.829 0.6,0.943 0.486,1 0.257,1",
        "0,0 0.257,0 0.343,0 0.457,0.086 0.514,0.2 0.543,0.4 0.543,0.486 0.457,0.543 0.229,0.543",
    ],
    "4": ["0.543,0.229 0,0.229 0.457,1", "0.429,0.486 0.286,0"],
    "5": [
        "0,0 0.257,0 0.371,0.029 0.457,0.086 0.514,0.2 0.571,0.371 0.543,0.486 0.429,0.543 "
        "0.171,0.543 0.286,1 0.743,1"
    ],
    "6": [
        "0.086,0.543 0,0.229 0.029,0.086 0.114,0 0.257,0 0.371,0.086 0.457,0.229 0.514,0.371 "
        "0.514,0.457 0.457,0.514 0.371,0.543 0.086,0.543",
        "0.571,1 0.371,0.914 0.2,0.743 0.086,0.543",
    ],
    "7": ["0.028,0.861 0.056,1 0.5,1 0,0"],
    "8": [
        "0.029,0.343 0,0.229 0,0.086 0.086,0 0.229,0 0.371,0.086 0.457,0.229 0.486,0.343 "
        "0.486,0.457 0.371,0.543 0.229,0.543 0.114,0.457 0.029,0.343",
        "0.143,0.8 0.143,0.657 "
        "0.257,0.571 0.4,0.571 0.514,0.657 0.6,0.8 0.6,0.914 0.514,1 0.371,1 0.229,0.914 "
        "0.143,0.8",
    ],
    "9": [
        "0.457,0.457 0.543,0.8 0.543,0.914 0.457,1 0.314,1 0.171,0.914 0.086,0.8 0.057,0.629 "
        "0.086,0.514 0.2,0.457 0.457,0.457",
        "0,0 0.2,0.086 0.371,0.257 0.457,0.457",
    ],
    "0": [
        "0.440,0.500 0.455,0.691 0.438,0.854 0.390,0.962 0.320,1.000 0.237,0.962 0.155,0.854 "
        "0.086,0.691 0.040,0.500 0.025,0.309 0.042,0.146 0.090,0.038 0.160,0.000 0.243,0.038 "
        "0.325,0.146 0.394,0.309 0.440,0.500"
    ],
}
SAMPLES = 48
MATCH = 0.11  # среднее расстояние (в высотах знака), при котором знак ещё узнан
MIN_H, MAX_H = 120.0, 900.0  # высота знаков подписи, мм

Pt = tuple[float, float]


def _sample(strokes: list[list[Pt]], n: int = SAMPLES) -> list[Pt]:
    total = sum(math.dist(s[i - 1], s[i]) for s in strokes for i in range(1, len(s)))
    if total <= 0:
        return [p for s in strokes for p in s][:n] or [(0.0, 0.0)]
    step = total / n
    out: list[Pt] = []
    for s in strokes:
        carry = 0.0
        out.append(s[0])
        for i in range(1, len(s)):
            a, b = s[i - 1], s[i]
            d = math.dist(a, b)
            k = step - carry
            while k <= d:
                t = k / d
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                k += step
            carry = d - (k - step)
    return out


def _parse(strokes: list[str]) -> list[list[Pt]]:
    return [[(float(x), float(y)) for x, y in (p.split(",") for p in s.split())] for s in strokes]


_TEMPLATE_POINTS = {ch: _sample(_parse(s)) for ch, s in TEMPLATES.items()}


def _chamfer(a: list[Pt], b: list[Pt]) -> float:
    da = sum(min(math.dist(p, q) for q in b) for p in a) / len(a)
    db = sum(min(math.dist(p, q) for q in a) for p in b) / len(b)
    return (da + db) / 2


@dataclass
class Glyph:
    segs: list[Seg]
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    @property
    def w(self) -> float:
        return self.x1 - self.x0


def _glyph(segs: list[Seg]) -> Glyph:
    xs = [p[0] for s in segs for p in (s.a, s.b)]
    ys = [p[1] for s in segs for p in (s.a, s.b)]
    return Glyph(segs, min(xs), min(ys), max(xs), max(ys))


def classify(g: Glyph) -> str | None:
    h = g.h
    points = _sample(
        [
            [((s.a[0] - g.x0) / h, (s.a[1] - g.y0) / h), ((s.b[0] - g.x0) / h, (s.b[1] - g.y0) / h)]
            for s in g.segs
        ]
    )
    best = min(((_chamfer(points, t), ch) for ch, t in _TEMPLATE_POINTS.items()))
    return best[1] if best[0] <= MATCH else None


def read(groups: list[list[Seg]]) -> list[tuple[float, float, str]]:
    """Числа, набранные знаками-линиями: (x, y центра, текст). Числа с точкой — площади,
    они не возвращаются."""
    glyphs = [_glyph(g) for g in groups if g]
    chars = [g for g in glyphs if MIN_H <= g.h <= MAX_H and g.w <= 1.2 * g.h]
    dots = [g for g in glyphs if g.h < MIN_H / 3 and g.w < MIN_H / 3]
    chars.sort(key=lambda g: g.x0)
    words: list[list[Glyph]] = []
    for g in chars:
        for word in words:
            last = word[-1]
            same_line = min(last.y1, g.y1) - max(last.y0, g.y0) > 0.5 * min(last.h, g.h)
            if (
                same_line
                and 0.7 <= g.h / last.h <= 1.4
                and -0.2 * g.h <= g.x0 - last.x1 <= 0.8 * g.h
            ):
                word.append(g)
                break
        else:
            words.append([g])
    out: list[tuple[float, float, str]] = []
    for word in words:
        x0, x1 = word[0].x0, word[-1].x1
        y0, y1 = min(g.y0 for g in word), max(g.y1 for g in word)
        h = y1 - y0
        if any(
            x0 - 0.2 * h <= d.x0 <= x1 + 0.4 * h and y0 - 0.2 * h <= d.y0 <= y0 + 0.3 * h
            for d in dots
        ):
            continue  # с точкой — площадь
        text = [classify(g) for g in word]
        if any(c is None for c in text):
            continue
        out.append(((x0 + x1) / 2, (y0 + y1) / 2, "".join(text)))  # type: ignore[arg-type]
    return out
