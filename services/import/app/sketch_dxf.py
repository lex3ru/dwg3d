"""A drawn plan as a DXF drawing: what a builder or a designer opens in their CAD.

Every floor is drawn in the model space, in meters ($INSUNITS = meters), the
floors side by side from left to right with a gap between, each titled above.
Layers: walls and partitions (outlines with a solid fill, openings cut out),
openings (jambs, window panes, door leaves and their swings), rooms (outlines)
and labels (number, name and area of each room).
"""
from __future__ import annotations

import math
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .dwg.config import load_config
from .sketch import _polys, plan_of, read_sketch

LAYERS = {"Стены": 7, "Перегородки": 8, "Колонны": 7, "Лестницы": 6, "Проёмы": 1, "Помещения": 3, "Подписи": 5}
GAP = 5.0           # meters between floors laid side by side
TEXT = 0.25         # label height, meters


def _outline(msp, geom, layer: str, dx: float, dy: float, fill: bool = False) -> None:
    for p in _polys(geom):
        if fill:
            hatch = msp.add_hatch(color=LAYERS[layer], dxfattribs={"layer": layer})
            for ring, outer in [(p.exterior, 1), *((r, 0) for r in p.interiors)]:
                points = [(x + dx, y + dy) for x, y in ring.coords[:-1]]
                hatch.paths.add_polyline_path(points, is_closed=True, flags=outer)
        for ring in [p.exterior, *p.interiors]:
            msp.add_lwpolyline([(x + dx, y + dy) for x, y in ring.coords[:-1]], close=True, dxfattribs={"layer": layer})


def _opening(msp, o, dx: float, dy: float) -> None:
    """The jambs, and a window's panes or a door's leaf with its swing."""
    (ux, uy), (cx, cy) = o.direction, o.center
    nx, ny = -uy, ux
    h, w = o.depth / 2, o.width / 2
    a, b = (cx - ux * w, cy - uy * w), (cx + ux * w, cy + uy * w)

    def line(p, q):
        msp.add_line((p[0] + dx, p[1] + dy), (q[0] + dx, q[1] + dy), dxfattribs={"layer": "Проёмы"})

    for c in (a, b):
        line((c[0] - nx * h, c[1] - ny * h), (c[0] + nx * h, c[1] + ny * h))
    if o.kind in ("window", "vitrage"):
        for k in ((-h / 3, h / 3) if o.kind == "window" else (0.0,)):
            line((a[0] + nx * k, a[1] + ny * k), (b[0] + nx * k, b[1] + ny * k))
    for hinge, tip in o.leaves:
        line(hinge, tip)
        # the swing: from the open leaf to where it closes, by the far jamb on the same face — the quarter between
        near, far = (a, b) if math.dist(hinge, a) < math.dist(hinge, b) else (b, a)
        closed = (hinge[0] + far[0] - near[0], hinge[1] + far[1] - near[1])
        start = math.degrees(math.atan2(tip[1] - hinge[1], tip[0] - hinge[0]))
        end = math.degrees(math.atan2(closed[1] - hinge[1], closed[0] - hinge[0]))
        lo, hi = (start, end) if (end - start) % 360 <= 180 else (end, start)     # DXF arcs go counter-clockwise
        msp.add_arc((hinge[0] + dx, hinge[1] + dy), math.dist(hinge, tip), lo, hi, dxfattribs={"layer": "Проёмы"})


def _stair(msp, st, dx: float, dy: float) -> None:
    """The flight: its outline, the lines between its treads, and an arrow from its foot up to its head."""
    _outline(msp, st.poly, "Лестницы", dx, dy)
    (ux, uy), c = st.direction, st.poly.centroid
    run = st.going * len(st.treads)
    foot, head = (c.x - ux * run / 2, c.y - uy * run / 2), (c.x + ux * run / 2, c.y + uy * run / 2)
    nx, ny, w = -uy, ux, st.width / 2

    def line(p, q):
        msp.add_line((p[0] + dx, p[1] + dy), (q[0] + dx, q[1] + dy), dxfattribs={"layer": "Лестницы"})

    for k in range(1, len(st.treads)):
        m = (foot[0] + ux * st.going * k, foot[1] + uy * st.going * k)
        line((m[0] - nx * w, m[1] - ny * w), (m[0] + nx * w, m[1] + ny * w))
    line(foot, head)
    tip = min(0.25, w / 2)
    back = (head[0] - ux * tip, head[1] - uy * tip)
    line((back[0] + nx * tip * 0.6, back[1] + ny * tip * 0.6), head)
    line((back[0] - nx * tip * 0.6, back[1] - ny * tip * 0.6), head)


def sketch_dxf(sketch: dict, out: Path) -> dict[str, tuple[float, float]]:
    """Write the plan to `out`; returns where each floor was moved to on the sheet (floor id → shift, meters)."""
    sketch = read_sketch(sketch)
    cfg = load_config({})
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    for name, color in LAYERS.items():
        doc.layers.add(name, color=color)
    msp = doc.modelspace()
    shifts: dict[str, tuple[float, float]] = {}
    x = 0.0
    for f in sorted(sketch["floors"], key=lambda f: (f["level"], f["elevation"])):
        if not f["walls"]:
            continue
        plan = plan_of(f, cfg)
        x0, y0, x1, y1 = plan.footprint.bounds if not plan.footprint.is_empty else plan.walls.bounds
        dx, dy = x - x0, -y0
        shifts[f["id"]] = (dx, dy)
        _outline(msp, plan.wall_parts.get("wall"), "Стены", dx, dy, fill=True)
        _outline(msp, plan.wall_parts.get("partition"), "Перегородки", dx, dy, fill=True)
        _outline(msp, plan.columns, "Колонны", dx, dy, fill=True)
        for st in plan.stairs:
            _stair(msp, st, dx, dy)
        for o in plan.openings:
            _opening(msp, o, dx, dy)
        for r in plan.rooms:
            _outline(msp, r.poly, "Помещения", dx, dy)
            p = r.poly.representative_point()
            text = "\\P".join(t for t in (" ".join(t for t in (r.number, r.name) if t), f"{r.area:.2f} м²") if t)
            m = msp.add_mtext(text, dxfattribs={"layer": "Подписи", "char_height": TEXT})
            m.set_location((p.x + dx, p.y + dy), attachment_point=5)
        title = msp.add_text(f["name"], height=TEXT * 2, dxfattribs={"layer": "Подписи"})
        title.set_placement((x, y1 - y0 + TEXT * 2), align=TextEntityAlignment.BOTTOM_LEFT)
        x += (x1 - x0) + GAP
    if not shifts:
        raise RuntimeError("В плане нет ни одной стены — выгружать нечего")
    doc.saveas(str(out))
    return shifts
