"""Разбиение чертежа на части: на одном листе модели обычно лежат планы нескольких
этажей рядом. Часть — связная группа фигур здания; между частями — пустое поле.
Что за часть — план этажа, рамка, штамп, таблица, фасад, разрез — узнаётся по её
подписи, названию листа в штампе и форме (R-061, R-062, ADR-0026)."""

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from app.modules.building.drawing import captions
from app.modules.building.drawing.layers import role
from app.modules.building.drawing.read import Drawing, Seg

CELL = 1000.0  # мм: шаг сетки, по которой ищутся связные группы
GAP = 3  # клеток пустоты, которые ещё не разделяют части
MIN_SEGS = 10  # меньше фигур здания — не этаж (одинокий знак)
STRUCTURE = {"wall", "partition", "window", "door", "column", "stair", "lift", "fill", "other"}
MIN_FLOOR = 5000.0  # мм: часть меньше — подпись, значок, узел; по умолчанию не этаж
TOL = 5.0  # мм: линии рамки и штампа сходятся точно — допуск на округление
ORTHO = 0.95  # доля длины горизонталей и вертикалей у таблицы и штампа
TABLE_TEXTS = 0.5  # у таблицы текстов не меньше этой доли от числа линий
STAMP_TEXTS = 0.3  # у штампа — не меньше этой
FRAME_INNER = 0.1  # части внутри занимают хотя бы эту долю габарита — это рамка листа
TITLED = 0.05  # название листа «план…» получает чертёж не меньше этой доли рамки
# штампы ГОСТ Р 21.101 (185 × 55, 40, 15 мм) — если рамка не нашлась: высота к ширине
STAMPS = (55 / 185, 40 / 185, 15 / 185)

Box = tuple[float, float, float, float]


@dataclass
class Part:
    key: str
    bbox: Box
    segs: int
    name: str = ""  # «План 3-го этажа», найденное на чертеже
    level: int | None = None  # номер этажа из названия
    preview: str = ""  # SVG-путь в квадрате 0..1000
    # что это: plan, roof, frame, stamp, table, facade, section, detail, scheme, site;
    # "" — не понять (R-061)
    kind: str = ""
    floor_like: bool = False  # предлагать ли этажом по умолчанию (R-061)
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class Sheet:
    """Лист: рамка и штамп в её правом нижнем углу."""

    frame: Box
    stamp: Box


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
        own = [segs[i] for i in idx]
        xs = [p[0] for s in own for p in (s.a, s.b)]
        ys = [p[1] for s in own for p in (s.a, s.b)]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        part = Part(key=f"p{g}", bbox=bbox, segs=len(idx))
        part.preview = _preview(own, bbox)
        part.extra["ortho"] = _ortho(own)
        parts.append(part)
    # слева направо, сверху вниз — как обычно раскладывают этажи на листе
    parts.sort(key=lambda p: (round(-p.bbox[3] / 20000), p.bbox[0]))
    for i, part in enumerate(parts, 1):
        part.key = f"p{i}"
    found = sheets(drawing)
    home = {p.key: _sheet_of(found, p.bbox) for p in parts}
    _shapes(drawing, parts, home)
    _names(drawing, parts, found, home)
    # этажом предлагается план размером с этаж; если ни один план не узнан по подписи —
    # любая часть такого размера, о которой ничего не известно
    planned = any(p.kind == "plan" for p in parts)
    for part in parts:
        x0, y0, x1, y1 = part.bbox
        part.floor_like = min(x1 - x0, y1 - y0) >= MIN_FLOOR and (
            part.kind == "plan" or (not part.kind and not planned))
        part.extra.pop("ortho", None)
    return parts


def _ortho(segs: list[Seg]) -> float:
    """Доля длины горизонталей и вертикалей: у таблицы и штампа — почти вся."""
    total = straight = 0.0
    for s in segs:
        d = math.dist(s.a, s.b)
        total += d
        if abs(s.a[0] - s.b[0]) < 1 or abs(s.a[1] - s.b[1]) < 1:
            straight += d
    return straight / total if total else 0.0


# ---------------------------------------------------------------- листы: рамка и штамп


def _runs(drawing: Drawing) -> tuple[dict[int, list[list[float]]], dict[int, list[list[float]]]]:
    """Горизонтали и вертикали чертежа любого слоя (рамка бывает и на слое, который разбор
    пропускает), отрезки одной прямой — склеены: {y: [[x0, x1], …]}, {x: [[y0, y1], …]}."""
    rows: dict[int, list[list[float]]] = defaultdict(list)
    cols: dict[int, list[list[float]]] = defaultdict(list)
    for s in drawing.segs:
        (ax, ay), (bx, by) = s.a, s.b
        if abs(ay - by) < 0.5:
            rows[round(ay)].append([min(ax, bx), max(ax, bx)])
        elif abs(ax - bx) < 0.5:
            cols[round(ax)].append([min(ay, by), max(ay, by)])
    return _merge(rows), _merge(cols)


def _merge(lines: dict[int, list[list[float]]]) -> dict[int, list[list[float]]]:
    out = {}
    for key, spans in lines.items():
        spans.sort()
        merged = [spans[0][:]]
        for a, b in spans[1:]:
            if a <= merged[-1][1] + TOL:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        out[key] = merged
    return out


def _covered(runs: dict[int, list[list[float]]], key: float, a: float, b: float) -> bool:
    """Отрезок [a, b] прямой key почти весь (95 %) лежит на линиях чертежа."""
    k = round(key)
    total = sum(max(0.0, min(hi, b) - max(lo, a))
                for kk in (k - 1, k, k + 1) for lo, hi in runs.get(kk, ()))
    return total >= 0.95 * (b - a)


def sheets(drawing: Drawing) -> list[Sheet]:
    """Листы на чертеже: прямоугольник рамки, в правом нижнем углу которого — штамп:
    прямоугольник с текстами, прижатый к правой и нижней сторонам рамки (ГОСТ Р 21.101)."""
    rows, cols = _runs(drawing)
    row_keys, col_keys = sorted(rows), sorted(cols)
    xy = np.array([(t.x, t.y) for t in drawing.texts]) if drawing.texts else np.zeros((0, 2))
    found: dict[tuple[int, int, int, int], Sheet] = {}
    for x, spans in cols.items():
        for y0, y1 in spans:
            if y1 - y0 < MIN_FLOOR:
                continue
            # правая сторона рамки: от её низа влево идёт нижняя сторона; она бывает длиннее
            # рамки (под графами на поле листа) — левая сторона — самая левая вертикаль во
            # всю высоту, до которой доходит и верхняя сторона
            for k in (round(y0) - 1, round(y0), round(y0) + 1):
                for start, right in rows.get(k, ()):
                    if abs(right - x) > TOL or right - start < MIN_FLOOR:
                        continue
                    lo = bisect.bisect_left(col_keys, start - TOL)
                    hi = bisect.bisect_right(col_keys, x - MIN_FLOOR)
                    left = next((float(c) for c in col_keys[lo:hi]
                                 if _covered(cols, c, y0, y1) and _covered(rows, y1, c, x)), None)
                    if left is None:
                        continue
                    frame = (left, y0, float(x), y1)
                    stamp = _stamp(rows, cols, row_keys, xy, frame)
                    if stamp is not None and not _grid(rows, row_keys, cols, col_keys, frame):
                        found[tuple(round(v / 10) for v in frame)] = Sheet(frame, stamp)  # type: ignore[index]
    return list(found.values())


def _grid(rows: dict[int, list[list[float]]], row_keys: list[int],
          cols: dict[int, list[list[float]]], col_keys: list[int], frame: Box) -> bool:
    """Таблица, а не рамка: внутри есть линии через всю ширину или высоту. В рамке такая
    линия бывает одна — верх штампа на листе А4."""
    x0, y0, x1, y1 = frame
    found = 0
    for keys, runs, a, b, lo, hi in ((row_keys, rows, x0, x1, y0, y1),
                                     (col_keys, cols, y0, y1, x0, x1)):
        inner = keys[bisect.bisect_right(keys, lo + TOL):bisect.bisect_left(keys, hi - TOL)]
        found += sum(1 for k in inner
                     if any(e - s >= 0.3 * (b - a) for s, e in runs[k]) and _covered(runs, k, a, b))
        if found >= 2:
            return True
    return False


def _stamp(rows: dict[int, list[list[float]]], cols: dict[int, list[list[float]]],
           row_keys: list[int], xy: np.ndarray, frame: Box) -> Box | None:
    """Штамп в правом нижнем углу рамки: верхняя сторона идёт от правой стороны рамки,
    левая — от нижней, в нём не меньше трёх текстов. Из вложенных граф — наибольший."""
    x0, y0, x1, y1 = frame
    width, height = x1 - x0, y1 - y0
    best: tuple[float, Box] | None = None
    lo = bisect.bisect_right(row_keys, y0 + TOL)
    hi = bisect.bisect_right(row_keys, y0 + 0.5 * height)
    for key in row_keys[lo:hi]:
        for left, right in rows[key]:
            w, h = x1 - left, key - y0
            # верх штампа доходит до правой стороны рамки, а бывает — и дальше, над графами
            # на поле листа
            if right < x1 - TOL or left > x1 or not 1.5 <= w / h <= 15 or w > width + TOL:
                continue
            if not _covered(cols, left, y0, key):
                continue
            inside = ((xy[:, 0] >= left) & (xy[:, 0] <= x1) & (xy[:, 1] >= y0)
                      & (xy[:, 1] <= key)).sum() if len(xy) else 0
            if inside >= 3 and (best is None or w * h > best[0]):
                best = (w * h, (left, y0, x1, float(key)))
    return best[1] if best else None


def _area(b: Box) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def _within(inner: Box, outer: Box, slack: float = 0.01) -> bool:
    tol = TOL + slack * max(outer[2] - outer[0], outer[3] - outer[1])
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def _contains(box: Box, x: float, y: float) -> bool:
    return box[0] - TOL <= x <= box[2] + TOL and box[1] - TOL <= y <= box[3] + TOL


def _overlap(a: Box, b: Box) -> float:
    """Какая доля a лежит в b."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0.0) * max(h, 0.0) / max(_area(a), 1.0)


def _sheet_of(found: list[Sheet], box: Box) -> Sheet | None:
    """Лист, в рамке которого лежит середина части (наименьший)."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    holders = [s for s in found
               if _contains(s.frame, cx, cy) and _area(box) <= 1.05 * _area(s.frame)]
    return min(holders, key=lambda s: _area(s.frame), default=None)


# ---------------------------------------------------------------- что за часть


def _shapes(drawing: Drawing, parts: list[Part], home: dict[str, Sheet | None]) -> None:
    """Вид части по форме: штамп — в углу рамки, рамка — лист, внутри которого другие
    части, таблица — сетка горизонталей и вертикалей с текстом в графах (R-061)."""
    xy = np.array([(t.x, t.y) for t in drawing.texts]) if drawing.texts else np.zeros((0, 2))
    for part in parts:
        sheet = home[part.key]
        x0, y0, x1, y1 = part.bbox
        w, h = x1 - x0, y1 - y0
        ortho = float(part.extra.get("ortho", 0.0))  # type: ignore[arg-type]
        texts = int(((xy[:, 0] >= x0) & (xy[:, 0] <= x1) & (xy[:, 1] >= y0)
                     & (xy[:, 1] <= y1)).sum()) if len(xy) else 0
        shape = min(w, h) / max(w, h, 1)
        inner = sum(_area(p.bbox) for p in parts if p is not part
                    and _within(p.bbox, part.bbox, 0) and _area(p.bbox) < _area(part.bbox))
        if sheet is not None and _overlap(part.bbox, sheet.stamp) >= 0.5:
            part.kind = "stamp"
        elif inner >= FRAME_INNER * _area(part.bbox):
            # рамка листа с чертежами внутри; мелочь внутри (логотип, значок) — не в счёт:
            # это рамка, слитая с планом
            part.kind = "frame"
        elif ortho >= ORTHO and texts >= TABLE_TEXTS * part.segs:
            part.kind = "table"
        elif (ortho >= ORTHO and texts >= STAMP_TEXTS * part.segs
              and any(abs(shape - r) <= 0.03 * r for r in STAMPS)):
            part.kind = "stamp"


# ---------------------------------------------------------------- названия


def _rank(c: captions.Caption) -> tuple[bool, bool, float]:
    # название чертежа важнее заголовка таблицы рядом, «план» — важнее прочего
    return (c.kind != "table", "план" in c.text.lower(), c.height)


def _apply(part: Part, c: captions.Caption) -> None:
    part.name = c.text
    if not part.kind:
        part.kind = c.kind
    # номер этажа — только у плана: «Таблица помещений 2-го этажа» — не этаж (R-062)
    part.level = captions.level(c.text) if part.kind == "plan" else None


def _names(drawing: Drawing, parts: list[Part], found: list[Sheet],
           home: dict[str, Sheet | None]) -> None:
    """Подпись достаётся одной части: той, в которой стоит, иначе — ближайшей над или под
    ней на том же листе. Подпись в штампе — название листа: его получает часть листа без
    своей подписи (R-062)."""
    own: dict[str, list[captions.Caption]] = defaultdict(list)
    titles: dict[int, list[captions.Caption]] = defaultdict(list)
    for c in captions.find(drawing.texts):
        sheet = min((s for s in found if _contains(s.frame, c.x, c.y)),
                    key=lambda s: _area(s.frame), default=None)
        if sheet is not None and _contains(sheet.stamp, c.x, c.y):
            titles[id(sheet)].append(c)
            continue
        holder = min((p for p in parts if p.kind != "frame" and _contains(p.bbox, c.x, c.y)),
                     key=lambda p: _area(p.bbox), default=None)
        if holder is None:
            holder = _nearest(parts, home, sheet, c)
        if holder is not None:
            own[holder.key].append(c)
    for part in parts:
        if own.get(part.key):
            _apply(part, max(own[part.key], key=_rank))
    for sheet in found:
        if not titles.get(id(sheet)):
            continue
        title = max(titles[id(sheet)], key=_rank)
        drawings = [p for p in parts if home[p.key] is sheet and not own.get(p.key)
                    and p.kind not in ("frame", "stamp", "table")]
        if not drawings:
            continue
        main = max(drawings, key=lambda p: _area(p.bbox))
        if title.kind in ("plan", "roof"):
            # план этажа — крупный чертёж листа, а не значок в углу
            if _area(main.bbox) >= TITLED * _area(sheet.frame):
                _apply(main, title)
            continue
        _apply(main, title)
        # «Фасады», «Разрезы» — о всех чертежах листа без своей подписи
        for p in drawings:
            p.kind = p.kind or title.kind


def _nearest(parts: list[Part], home: dict[str, Sheet | None], sheet: Sheet | None,
             c: captions.Caption) -> Part | None:
    """Часть того же листа, над или под которой стоит подпись, — ближайшая."""
    best: tuple[tuple[float, bool], Part] | None = None
    for p in parts:
        if p.kind in ("frame", "stamp") or home[p.key] is not sheet:
            continue
        x0, y0, x1, y1 = p.bbox
        w, h = x1 - x0, y1 - y0
        if not x0 - 0.1 * w <= c.x <= x1 + 0.1 * w:
            continue
        gap = y0 - c.y if c.y < y0 else max(0.0, c.y - y1)
        if gap > max(0.35 * h, 3 * c.height):
            continue
        # при равных — часть под подписью: название пишут над изображением
        key = (gap, c.y < y0)
        if best is None or key < best[0]:
            best = (key, p)
    return best[1] if best else None


def _preview(segs: list[Seg], bbox: Box) -> str:
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
