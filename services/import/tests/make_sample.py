"""Synthetic two-storey DXF exercising the pipeline's edge cases.

Per floor (drawn in CENTIMETERS, $INSUNITS = 0 -> units must be guessed):
* 12 x 8 m exterior wall, 30 cm, drawn as outer face + inner face + an
  axis line on the SAME layer (must not be doubled),
* interior partition (12 cm, two lines) with a 0.9 m door gap with end caps,
  and a 5 mm drawing gap where it meets the exterior wall (must be snapped),
* a WINDOW block (1.5 m) inserted on the continuous south wall,
* grid axes with labelled bubbles, a title "План N-го этажа",
* floor 2 is drawn 30 m to the right / 5 m up (sheet layout), level mark.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf

CM = 100.0


def rect(msp, x0, y0, x1, y1, layer):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b, dxfattribs={"layer": layer})


def floor(msp, ox, oy, level, mark, *, office="Кабинет", split=False, left=True):
    """`split`: a wall divides the office at x = 8.5 m; `left=False`: the room on the left is not there
    (the building on this floor starts at the partition); `office`: the name written in the office."""
    s = CM
    W, H, t = 12 * s, 8 * s, 0.3 * s
    x0 = 0 if left else 5 * s
    L = lambda a, b: msp.add_line((ox + a[0], oy + a[1]), (ox + b[0], oy + b[1]), dxfattribs={"layer": "A-WALL"})
    rect(msp, ox + x0, oy, ox + W, oy + H, "A-WALL")                  # outer face
    rect(msp, ox + x0 + t, oy + t, ox + W - t, oy + H - t, "A-WALL")  # inner face
    rect(msp, ox + x0 + t / 2, oy + t / 2, ox + W - t / 2, oy + H - t / 2, "A-WALL")  # axis on wall layer
    if split:                                                        # a 12 cm wall across the office
        for x in (8.5 * s, 8.62 * s):
            L((x, t), (x, H - t))
    if left:
        # partition at x = 5 m, 12 cm thick, door gap 3.0..3.9 m, 5 mm gap at the bottom
        px, pt = 5 * s, 0.12 * s
        y_bot, y_top = t + 0.5, H - t                                    # 0.5 cm = 5 mm drawing gap
        d0, d1 = 3.0 * s, 3.9 * s
        for x in (px, px + pt):
            L((x, y_bot), (x, d0))
            L((x, d1), (x, y_top))
        L((px, d0), (px + pt, d0))                                       # end caps
        L((px, d1), (px + pt, d1))
        # door swing arc: hinge at the lower jamb, leaf 0.9 m drawn open into the right room
        msp.add_arc((ox + px + pt, oy + d0), 0.9 * s, 0, 90, dxfattribs={"layer": "0"})
        msp.add_line((ox + px + pt, oy + d0), (ox + px + pt + 0.9 * s, oy + d0), dxfattribs={"layer": "0"})
        # stair flight: 8 treads, 1.2 m wide, 0.3 m going (unmapped layer)
        for k in range(9):
            y = 1.0 * s + k * 0.3 * s
            msp.add_line((ox + 1.0 * s, oy + y), (ox + 2.2 * s, oy + y), dxfattribs={"layer": "ТОНКАЯ"})
    # 10 cm insulation on the outside of the north wall, as a hatch
    ins = msp.add_hatch(dxfattribs={"layer": "Утеплитель"})
    ins.paths.add_polyline_path([(ox + x0, oy + H), (ox + W, oy + H), (ox + W, oy + H + 0.1 * s),
                                 (ox + x0, oy + H + 0.1 * s)])
    # window block on the south wall (continuous wall)
    msp.add_blockref("WINDOW", (ox + 8 * s, oy + t / 2), dxfattribs={"layer": "A-GLAZ"})
    # grid
    for i, x in enumerate((0.15 * s, W - 0.15 * s)):
        msp.add_line((ox + x, oy - 2 * s), (ox + x, oy + H + 2 * s), dxfattribs={"layer": "A-GRID"})
        bref = msp.add_blockref("AXIS", (ox + x, oy - 2.4 * s), dxfattribs={"layer": "A-GRID"})
        bref.add_auto_attribs({"AXIS": str(i + 1)})
    for i, y in enumerate((0.15 * s, H - 0.15 * s)):
        msp.add_line((ox - 2 * s, oy + y), (ox + W + 2 * s, oy + y), dxfattribs={"layer": "A-GRID"})
        bref = msp.add_blockref("AXIS", (ox - 2.4 * s, oy + y), dxfattribs={"layer": "A-GRID"})
        bref.add_auto_attribs({"AXIS": "АБ"[i]})
    msp.add_text(f"План {level}-го этажа", height=0.5 * s, dxfattribs={"layer": "TEXT"}).set_placement(
        (ox + max(3 * s, x0 + 0.5 * s), oy + H + 1.2 * s))
    msp.add_text(mark, height=0.25 * s, dxfattribs={"layer": "MARKS"}).set_placement(
        (ox + max(2 * s, x0 + 0.5 * s), oy + 2 * s))
    at = (ox + (6.5 if split else 8) * s, oy + 4 * s)
    msp.add_text(office, height=0.3 * s, dxfattribs={"layer": "TEXT"}).set_placement(at)


def make(path: Path, changed: bool = False):
    """`changed`: the next version of the drawing — on floor 1 the office divided by a wall, on floor 2 the room
    on the left gone and the office renamed."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0
    s = CM
    win = doc.blocks.new("WINDOW")
    for y in (-0.15 * s, -0.05 * s, 0.05 * s, 0.15 * s):
        win.add_line((-0.75 * s, y), (0.75 * s, y))
    ax = doc.blocks.new("AXIS")
    ax.add_circle((0, 0), 0.4 * s)
    ax.add_attdef("AXIS", (0, 0), dxfattribs={"height": 0.3 * s})
    msp = doc.modelspace()
    floor(msp, 0, 0, 1, "±0,000", split=changed)
    floor(msp, 30 * s, 5 * s, 2, "+3,300", **({"office": "Ординаторская", "left": False} if changed else {}))
    doc.saveas(path)
    return path


if __name__ == "__main__":
    make(Path(sys.argv[1] if len(sys.argv) > 1 else "sample.dxf"), changed="--changed" in sys.argv)
