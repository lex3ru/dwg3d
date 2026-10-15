"""An office building for the load test, as a DXF the import understands (drawn like services/import/tests/make_sample.py).

    python tools/acceptance/make_office.py out.dxf [floors]

Each floor: 60 x 14 m, a corridor along the middle, ten offices on each side with a door to the corridor,
the name of each office written in it — 21 rooms a floor. Drawn in centimetres; floors side by side.
"""
from __future__ import annotations

import sys
from pathlib import Path

import ezdxf

S = 100.0                                   # centimetres in a metre
W, H, T, P = 60.0, 14.0, 0.3, 0.12          # floor size, outer wall, partition (metres)
C0, C1 = 6.0, 8.0                           # the corridor between these y
ROOMS = 10                                  # offices on each side
DOOR = 0.9


def floor(msp, ox: float, oy: float, level: int) -> None:
    def line(a, b, layer="A-WALL"):
        msp.add_line((ox + a[0] * S, oy + a[1] * S), (ox + b[0] * S, oy + b[1] * S), dxfattribs={"layer": layer})

    def rect(x0, y0, x1, y1):
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        for a, b in zip(pts, pts[1:]):
            line(a, b)

    rect(0, 0, W, H)                                   # outer face
    rect(T, T, W - T, H - T)                           # inner face
    step = (W - 2 * T) / ROOMS
    # the corridor walls, a door into each office; y0 is the face towards the offices of that side
    for y0, y1 in ((C0 - P, C0), (C1, C1 + P)):
        x = T
        for k in range(ROOMS):
            door = T + k * step + step / 2 - DOOR / 2
            for y in (y0, y1):
                line((x, y), (door, y))
            line((door, y0), (door, y1))                # end caps at the door
            line((door + DOOR, y0), (door + DOOR, y1))
            x = door + DOOR
        for y in (y0, y1):
            line((x, y), (W - T, y))
    # partitions between offices, both sides of the corridor
    for k in range(1, ROOMS):
        px = T + k * step - P / 2
        for a, b in ((T, C0 - P), (C1 + P, H - T)):
            for x in (px, px + P):
                line((x, a), (x, b))
    for side, y in (("Ю", C0 / 2), ("С", (C1 + H) / 2)):
        for k in range(ROOMS):
            msp.add_text(f"Кабинет {level}{side}{k + 1:02d}", height=0.25 * S, dxfattribs={"layer": "TEXT"}).set_placement(
                (ox + (T + k * step + 0.5) * S, oy + y * S))
    msp.add_text("Коридор", height=0.25 * S, dxfattribs={"layer": "TEXT"}).set_placement(
        (ox + W / 2 * S, oy + (C0 + C1) / 2 * S))
    msp.add_text(f"План {level}-го этажа", height=0.5 * S, dxfattribs={"layer": "TEXT"}).set_placement(
        (ox + 3 * S, oy + (H + 1.2) * S))
    msp.add_text(f"+{(level - 1) * 3.3:.3f}".replace(".", ","), height=0.25 * S, dxfattribs={"layer": "MARKS"}).set_placement(
        (ox + 2 * S, oy + 2 * S))


def make(path: Path, floors: int = 5) -> Path:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0
    msp = doc.modelspace()
    for i in range(floors):
        floor(msp, i * (W + 20) * S, 0, i + 1)
    doc.saveas(path)
    return path


if __name__ == "__main__":
    make(Path(sys.argv[1] if len(sys.argv) > 1 else "office.dxf"), int(sys.argv[2]) if len(sys.argv) > 2 else 5)
