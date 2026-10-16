"""Печать и выгрузка плана этажа (5.1.8): PDF листами А4/А3 в масштабе с рамкой и
основной надписью; DXF в миллиметрах по слоям."""

import io
import math
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

import ezdxf
from ezdxf.enums import TextEntityAlignment

from app.modules.building import geometry
from app.modules.building.plan import Opening, Plan, Wall

PAPERS = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}  # альбомная, мм
SCALES = [20, 25, 50, 75, 100, 150, 200, 250, 500, 1000]
MARGIN = 10.0  # поля листа, мм
TITLE_H = 18.0  # основная надпись, мм


Pt = tuple[float, float]


# ---------------------------------------------------------------- геометрия рисунка

def _line(plan: Plan, wall: Wall) -> list[Pt]:
    a, b = plan.nodes[wall.a], plan.nodes[wall.b]
    return geometry.arc_points(a, b, wall.bulge)


def _length(points: list[Pt]) -> float:
    return sum(math.dist(points[i - 1], points[i]) for i in range(1, len(points)))


def _at(points: list[Pt], s: float) -> tuple[Pt, Pt]:
    left = max(0.0, s)
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        d = math.dist(a, b)
        if left <= d or i == len(points) - 1:
            t = min(left / d, 1) if d else 0
            direction = ((b[0] - a[0]) / d, (b[1] - a[1]) / d) if d else (1.0, 0.0)
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), direction
        left -= d
    return points[0], (1.0, 0.0)


def _slice(points: list[Pt], s0: float, s1: float) -> list[Pt]:
    out = [_at(points, s0)[0]]
    acc = 0.0
    for i in range(1, len(points)):
        acc += math.dist(points[i - 1], points[i])
        if s0 < acc < s1:
            out.append(points[i])
    out.append(_at(points, s1)[0])
    return out


def _join_extensions(plan: Plan) -> dict[str, float]:
    """Насколько продлить стену за узел, где сходятся несколько стен: углы без щели."""
    count: dict[str, int] = {}
    thick: dict[str, float] = {}
    for w in plan.walls:
        for n in (w.a, w.b):
            count[n] = count.get(n, 0) + 1
            thick[n] = max(thick.get(n, 0), w.thickness)
    return {n: thick[n] / 2 for n, c in count.items() if c >= 2}


def _extend(points: list[Pt], e0: float, e1: float) -> list[Pt]:
    out = list(points)
    if len(out) < 2:
        return out
    if e0:
        (ax, ay), (bx, by) = out[0], out[1]
        d = math.dist(out[0], out[1]) or 1
        out[0] = (ax - (bx - ax) / d * e0, ay - (by - ay) / d * e0)
    if e1:
        (ax, ay), (bx, by) = out[-2], out[-1]
        d = math.dist(out[-2], out[-1]) or 1
        out[-1] = (bx + (bx - ax) / d * e1, by + (by - ay) / d * e1)
    return out


def _band(points: list[Pt], width: float) -> list[Pt]:
    half = width / 2
    left, right = [], []
    for i, p in enumerate(points):
        prev, nxt = points[max(0, i - 1)], points[min(len(points) - 1, i + 1)]
        d = math.dist(prev, nxt) or 1
        n = (-(nxt[1] - prev[1]) / d, (nxt[0] - prev[0]) / d)
        left.append((p[0] + n[0] * half, p[1] + n[1] * half))
        right.append((p[0] - n[0] * half, p[1] - n[1] * half))
    return left + right[::-1]


def _rect(x: float, y: float, w: float, d: float, angle: float) -> list[Pt]:
    r = math.radians(angle)
    c, s = math.cos(r), math.sin(r)
    return [(x + u * c - v * s, y + u * s + v * c)
            for u, v in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2))]


@dataclass
class Drawing:
    """Плоский рисунок плана: что и каким слоем рисовать."""

    walls: list[tuple[str, list[Pt]]]  # (слой, замкнутый контур)
    lines: list[tuple[str, list[Pt]]]  # (слой, ломаная)
    arcs: list[tuple[str, Pt, float, float, float]]  # (слой, центр, радиус, от°, до°)
    texts: list[tuple[str, Pt, str, float]]  # (слой, точка, текст, высота мм на плане)
    bbox: tuple[float, float, float, float]


def drawing(plan: Plan, rooms: list[dict[str, Any]], lifts: list[dict[str, Any]],
            floor_id: str) -> Drawing:
    walls: list[tuple[str, list[Pt]]] = []
    lines: list[tuple[str, list[Pt]]] = []
    arcs: list[tuple[str, Pt, float, float, float]] = []
    texts: list[tuple[str, Pt, str, float]] = []
    ext = _join_extensions(plan)
    by_wall: dict[str, list[Opening]] = {}
    for o in plan.openings:
        by_wall.setdefault(o.wall, []).append(o)
    for w in plan.walls:
        if w.a not in plan.nodes or w.b not in plan.nodes:
            continue
        line = _line(plan, w)
        length = _length(line)
        layer = "Стены несущие" if w.kind == "bearing" else "Перегородки"
        cursor = 0.0
        ops = sorted(by_wall.get(w.id, []), key=lambda o: o.at)
        pieces = []
        for o in ops:
            s0 = max(0.0, o.at - o.width / 2)
            if s0 > cursor:
                pieces.append((cursor, s0))
            cursor = max(cursor, min(length, o.at + o.width / 2))
        if cursor < length:
            pieces.append((cursor, length))
        for s0, s1 in pieces:
            piece = _extend(_slice(line, s0, s1), ext.get(w.a, 0) if s0 == 0 else 0,
                            ext.get(w.b, 0) if s1 == length else 0)
            walls.append((layer, _band(piece, w.thickness)))
        for o in ops:
            _opening(o, w, line, lines, arcs)
    for c in plan.columns:
        walls.append(("Колонны", _rect(c.x, c.y, c.w, c.d, c.angle) if not c.round else
                      [(c.x + c.w / 2 * math.cos(t / 16 * math.tau),
                        c.y + c.d / 2 * math.sin(t / 16 * math.tau)) for t in range(16)]))
    for st in plan.stairs:
        r = math.radians(st.angle)

        def to_w(u: float, v: float, st=st, r=r) -> Pt:
            return (st.x + u * math.cos(r) - v * math.sin(r),
                    st.y + u * math.sin(r) + v * math.cos(r))
        outline = [to_w(0, -st.width / 2), to_w(st.length, -st.width / 2),
                   to_w(st.length, st.width / 2), to_w(0, st.width / 2), to_w(0, -st.width / 2)]
        lines.append(("Лестницы", outline))
        for i in range(1, st.steps):
            u = st.length * i / st.steps
            lines.append(("Лестницы", [to_w(u, -st.width / 2), to_w(u, st.width / 2)]))
        lines.append(("Лестницы", [to_w(st.length * 0.1, 0), to_w(st.length * 0.9, 0)]))
        lines.append(("Лестницы", [to_w(st.length * 0.9 - 250, 150), to_w(st.length * 0.9, 0),
                                   to_w(st.length * 0.9 - 250, -150)]))
    for lift in lifts:
        if floor_id not in [str(f) for f in lift["floor_ids"]]:
            continue
        r = _rect(lift["x"], lift["y"], lift["w"], lift["d"], lift["angle"])
        lines.append(("Лифты", [*r, r[0]]))
        lines.append(("Лифты", [r[0], r[2]]))
        lines.append(("Лифты", [r[1], r[3]]))
        if lift.get("name"):
            texts.append(("Лифты", (lift["x"], lift["y"]), lift["name"], 250))
    for room in rooms:
        if room.get("outline"):
            lines.append(("Помещения", [*map(tuple, room["outline"]), tuple(room["outline"][0])]))
        x, y = room["x"], room["y"]
        if room.get("number"):
            texts.append(("Помещения", (x, y + 150), room["number"], 300))
        if room.get("name"):
            texts.append(("Помещения", (x, y - 250), room["name"], 200))
        texts.append(("Помещения", (x, y - 550), f"{room['area']:.2f} м²".replace(".", ","), 180))
    pts = [p for _, poly in walls for p in poly] + [p for _, poly in lines for p in poly]
    if not pts:
        pts = [(0.0, 0.0), (10000.0, 10000.0)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return Drawing(walls, lines, arcs, texts, (min(xs), min(ys), max(xs), max(ys)))


def _opening(o: Opening, w: Wall, line: list[Pt], lines: list, arcs: list) -> None:
    (cx, cy), (dx, dy) = _at(line, o.at)
    n = (-dy, dx)
    half, t = o.width / 2, w.thickness / 2

    def p(u: float, v: float) -> Pt:
        return (cx + dx * u + n[0] * v, cy + dy * u + n[1] * v)

    lines.append(("Проёмы", [p(-half, t), p(-half, -t)]))
    lines.append(("Проёмы", [p(half, t), p(half, -t)]))
    if o.kind in ("window", "glazing"):
        for v in ((-t / 3, t / 3) if o.kind == "window" else (-t / 2, 0, t / 2)):
            lines.append(("Проёмы", [p(-half, v), p(half, v)]))
    elif o.kind == "door":
        sign = 1 if o.side == "left" else -1
        hinge_u = -half if o.hinge == "start" else half
        free_u = -hinge_u
        h = p(hinge_u, sign * t)
        leaf = p(hinge_u, sign * (t + o.width))
        lines.append(("Проёмы", [h, leaf]))
        a0 = math.degrees(math.atan2(leaf[1] - h[1], leaf[0] - h[0]))
        f = p(free_u, sign * t)
        a1 = math.degrees(math.atan2(f[1] - h[1], f[0] - h[0]))
        start, end = (a0, a1) if ((a1 - a0) % 360) < 180 else (a1, a0)
        arcs.append(("Проёмы", h, o.width, start, end))


# ---------------------------------------------------------------- PDF

@dataclass
class Sheet:
    x0: float
    y0: float
    w: float
    h: float
    col: int
    row: int


def layout(d: Drawing, paper: str, orientation: str, scale: int | None
           ) -> tuple[int, list[Sheet], float, float]:
    pw, ph = PAPERS[paper]
    if orientation == "portrait":
        pw, ph = ph, pw
    aw, ah = pw - 2 * MARGIN, ph - 2 * MARGIN - TITLE_H
    minx, miny, maxx, maxy = d.bbox
    pad = 500
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    width, height = maxx - minx, maxy - miny
    if scale is None:  # самый крупный стандартный масштаб, при котором этаж — на одном листе
        scale = next((s for s in SCALES if width / s <= aw and height / s <= ah), SCALES[-1])
    sw, sh = aw * scale, ah * scale
    cols, rows = max(1, math.ceil(width / sw)), max(1, math.ceil(height / sh))
    # лист по центру рисунка, если он один
    ox = minx - (cols * sw - width) / 2
    oy = maxy + (rows * sh - height) / 2
    sheets = [Sheet(ox + c * sw, oy - (r + 1) * sh, sw, sh, c, r)
              for r in range(rows) for c in range(cols)]
    return scale, sheets, pw, ph


def _svg(d: Drawing, sheet: Sheet, scale: int, aw: float, ah: float,
         overlays: list[dict[str, Any]] | None = None) -> str:
    def tx(p: Pt) -> str:
        return f"{(p[0] - sheet.x0) / scale:.2f},{(sheet.y0 + sheet.h - p[1]) / scale:.2f}"

    stroke = {"Стены несущие": "#000", "Перегородки": "#555"}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{aw}mm" height="{ah}mm" '
             f'viewBox="0 0 {aw} {ah}"><g>']
    for layer, poly in d.lines:
        if layer == "Помещения":
            parts.append(f'<polyline points="{" ".join(tx(p) for p in poly)}" fill="#f2f5fa" '
                         f'stroke="none"/>')
    for layer, poly in d.walls:
        color = stroke.get(layer, "#666")
        parts.append(f'<polygon points="{" ".join(tx(p) for p in poly)}" fill="{color}"/>')
    for layer, poly in d.lines:
        if layer != "Помещения":
            parts.append(f'<polyline points="{" ".join(tx(p) for p in poly)}" fill="none" '
                         f'stroke="#222" stroke-width="0.18"/>')
    # поверх плана — фигуры модулей выше (предметы проекта): контур, заливка, пунктир
    for o in overlays or []:
        dash = ' stroke-dasharray="0.8,0.5"' if o.get("dash") else ""
        parts.append(f'<polygon points="{" ".join(tx(tuple(p)) for p in o["points"])}" '
                     f'fill="{o.get("fill", "none")}" fill-opacity="{o.get("opacity", 0.35)}" '
                     f'stroke="{o.get("stroke", "#000")}" stroke-width="0.25"{dash}/>')
    for _, center, radius, start, end in d.arcs:
        a = (center[0] + radius * math.cos(math.radians(start)),
             center[1] + radius * math.sin(math.radians(start)))
        b = (center[0] + radius * math.cos(math.radians(end)),
             center[1] + radius * math.sin(math.radians(end)))
        r = radius / scale
        parts.append(f'<path d="M{tx(a)} A{r:.2f},{r:.2f} 0 0 1 {tx(b)}" fill="none" '
                     f'stroke="#222" stroke-width="0.13"/>')
    for _, p, text, size in d.texts:
        mm = max(1.6, min(4.0, size / scale))
        parts.append(f'<text x="{tx(p).split(",")[0]}" y="{tx(p).split(",")[1]}" '
                     f'font-size="{mm:.2f}" text-anchor="middle" font-family="DejaVu Sans" '
                     f'fill="#111">{escape(text)}</text>')
    parts.append("</g></svg>")
    return "".join(parts)


def fit_svg(d: Drawing, aw: float, ah: float, overlays: list[dict[str, Any]]) -> tuple[str, int]:
    """Весь этаж на одном листе aw × ah мм в самом крупном стандартном масштабе — с фигурами
    поверх плана. Масштаб — для подписи."""
    minx, miny, maxx, maxy = d.bbox
    pad = 500
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    width, height = maxx - minx, maxy - miny
    scale = next((s for s in SCALES if width / s <= aw and height / s <= ah), SCALES[-1])
    sw, sh = aw * scale, ah * scale
    sheet = Sheet(minx - (sw - width) / 2, miny - (sh - height) / 2, sw, sh, 0, 0)
    return _svg(d, sheet, scale, aw, ah, overlays), scale


def pdf(d: Drawing, *, paper: str, orientation: str, scale: int | None, title: str,
        organization: str, floor: str) -> bytes:
    from weasyprint import HTML

    scale, sheets, pw, ph = layout(d, paper, orientation, scale)
    aw, ah = pw - 2 * MARGIN, ph - 2 * MARGIN - TITLE_H
    total = len(sheets)
    pages = []
    for i, sheet in enumerate(sheets, 1):
        pages.append(f"""
<section class="sheet">
  <div class="draw">{_svg(d, sheet, scale, aw, ah)}</div>
  <table class="title"><tr>
    <td class="org">{escape(organization)}</td>
    <td class="name">{escape(title)}<br><b>{escape(floor)}</b></td>
    <td>Масштаб 1:{scale}</td>
    <td>Лист {i} из {total}</td>
    <td>{datetime.now():%d.%m.%Y}</td>
  </tr></table>
</section>""")
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><style>
@page {{ size: {pw}mm {ph}mm; margin: {MARGIN}mm; }}
body {{ margin: 0; font-family: "DejaVu Sans", sans-serif; font-size: 8pt; }}
.sheet {{ width: {aw}mm; height: {ph - 2 * MARGIN}mm; page-break-after: always;
  border: 0.5mm solid #000; box-sizing: border-box; position: relative; }}
.sheet:last-child {{ page-break-after: auto; }}
.draw {{ height: {ah - 1}mm; overflow: hidden; }}
.title {{ position: absolute; bottom: 0; left: 0; right: 0; height: {TITLE_H}mm;
  border-collapse: collapse; width: 100%; }}
.title td {{ border-top: 0.5mm solid #000; border-left: 0.3mm solid #000; padding: 1mm 2mm;
  vertical-align: middle; }}
.title td:first-child {{ border-left: none; }}
.title .name {{ width: 40%; }}
.title .org {{ width: 25%; }}
</style></head><body>{"".join(pages)}</body></html>"""
    return HTML(string=html).write_pdf()


# ---------------------------------------------------------------- DXF

LAYER_COLORS = {"Стены несущие": 7, "Перегородки": 8, "Проёмы": 4, "Колонны": 7,
                "Лестницы": 2, "Лифты": 5, "Помещения": 3}


def dxf(d: Drawing) -> bytes:
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 4  # миллиметры
    for name, color in LAYER_COLORS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    for layer, poly in d.walls:
        msp.add_lwpolyline(poly, close=True, dxfattribs={"layer": layer})
        hatch = msp.add_hatch(color=LAYER_COLORS.get(layer, 7), dxfattribs={"layer": layer})
        hatch.paths.add_polyline_path(poly, is_closed=True)
    for layer, poly in d.lines:
        msp.add_lwpolyline(poly, dxfattribs={"layer": layer})
    for layer, center, radius, start, end in d.arcs:
        msp.add_arc(center, radius, start, end, dxfattribs={"layer": layer})
    for layer, p, text, size in d.texts:
        msp.add_text(text, height=size, dxfattribs={"layer": layer}).set_placement(
            p, align=TextEntityAlignment.MIDDLE_CENTER)
    out = io.StringIO()
    doc.write(out)
    return out.getvalue().encode("utf-8")
