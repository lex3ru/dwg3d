"""Простые 3D-модели медицинского оборудования для базового каталога — там, где готовых
свободных моделей нет (кушетки, каталка, купольные камеры, ростомер, УЗИ…).

Модели собираются из коробок, цилиндров и полусфер, в метрах, Y — вверх, перед смотрит
в −Z (как у предмета на плане — на +Y). Габариты — примерно по типу: в каталоге модель
всё равно вписывается в габариты типа. Запуск:

    uv run python tools/models3d.py app/modules/catalog/models3d
"""

import json
import math
import struct
import sys
from pathlib import Path

Color = tuple[float, float, float]

WHITE: Color = (0.94, 0.95, 0.96)
STEEL: Color = (0.72, 0.75, 0.78)
DARK: Color = (0.17, 0.18, 0.21)
GREY: Color = (0.45, 0.48, 0.52)
PAD: Color = (0.31, 0.62, 0.64)  # обивка кушеток
PAD2: Color = (0.78, 0.71, 0.60)
SCREEN: Color = (0.10, 0.22, 0.30)
GLOW: Color = (0.97, 0.98, 1.0)
BLUE: Color = (0.27, 0.48, 0.80)
RED: Color = (0.80, 0.22, 0.20)
ORANGE: Color = (0.92, 0.52, 0.16)
GLASS: Color = (0.75, 0.86, 0.92)


class Model:
    def __init__(self) -> None:
        # материал → (вершины, нормали)
        self.parts: dict[tuple[Color, bool, float], tuple[list[float], list[float]]] = {}

    def _tri(self, key: tuple[Color, bool, float], a, b, c) -> None:  # type: ignore[no-untyped-def]
        pos, nor = self.parts.setdefault(key, ([], []))
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        length = math.sqrt(sum(x * x for x in n)) or 1.0
        n = tuple(x / length for x in n)
        for p in (a, b, c):
            pos.extend(p)
            nor.extend(n)

    def quad(self, key, a, b, c, d) -> None:  # type: ignore[no-untyped-def]
        self._tri(key, a, b, c)
        self._tri(key, a, c, d)

    def box(
        self,
        x0: float,
        y0: float,
        z0: float,
        x1: float,
        y1: float,
        z1: float,
        color: Color,
        glow: bool = False,
        alpha: float = 1.0,
    ) -> None:
        k = (color, glow, alpha)
        p = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        # индексы: x*4 + y*2 + z
        for f in (
            (0, 1, 3, 2),
            (4, 6, 7, 5),
            (0, 4, 5, 1),
            (2, 3, 7, 6),
            (0, 2, 6, 4),
            (1, 5, 7, 3),
        ):
            self.quad(k, *(p[i] for i in f))

    def cyl(
        self,
        cx: float,
        cy: float,
        cz: float,
        r: float,
        h: float,
        color: Color,
        axis: str = "y",
        n: int = 20,
        glow: bool = False,
        alpha: float = 1.0,
        r2: float | None = None,
    ) -> None:
        """Цилиндр (или усечённый конус, r2) от точки (cx, cy, cz) вдоль оси на h."""
        k = (color, glow, alpha)
        r2 = r if r2 is None else r2

        def at(t: float, rr: float, s: float):  # type: ignore[no-untyped-def]
            u, v = rr * math.cos(t), rr * math.sin(t)
            if axis == "y":
                return (cx + u, cy + s, cz + v)
            if axis == "x":
                return (cx + s, cy + u, cz + v)
            return (cx + u, cy + v, cz + s)

        for i in range(n):
            t0, t1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            a, b, c, d = at(t0, r, 0), at(t1, r, 0), at(t1, r2, h), at(t0, r2, h)
            self.quad(k, a, d, c, b)
            self._tri(k, at(0, 0, 0), a, b)
            self._tri(k, at(0, 0, h), c, d)

    def dome(
        self,
        cx: float,
        cy: float,
        cz: float,
        r: float,
        color: Color,
        down: bool = True,
        alpha: float = 1.0,
    ) -> None:
        """Полусфера с плоской стороной на высоте cy; down — купол вниз (камера на потолке)."""
        k = (color, False, alpha)
        rings, n = 6, 20
        sgn = -1 if down else 1

        def at(i: int, j: int):  # type: ignore[no-untyped-def]
            phi = (math.pi / 2) * i / rings
            t = 2 * math.pi * j / n
            return (
                cx + r * math.cos(phi) * math.cos(t),
                cy + sgn * r * math.sin(phi),
                cz + r * math.cos(phi) * math.sin(t),
            )

        for i in range(rings):
            for j in range(n):
                a, b, c, d = at(i, j), at(i, j + 1), at(i + 1, j + 1), at(i + 1, j)
                if down:
                    self.quad(k, a, b, c, d)
                else:
                    self.quad(k, a, d, c, b)

    def legs(
        self,
        x0: float,
        z0: float,
        x1: float,
        z1: float,
        h: float,
        r: float = 0.018,
        color: Color = STEEL,
        wheels: bool = False,
    ) -> None:
        for x in (x0, x1):
            for z in (z0, z1):
                base = 0.06 if wheels else 0
                self.cyl(x, base, z, r, h - base, color)
                if wheels:
                    self.cyl(x - 0.02, 0.03, z, 0.03, 0.04, DARK, axis="x")

    def glb(self) -> bytes:
        materials, meshes, accessors, views = [], [], [], []
        blob = bytearray()
        for (color, glow, alpha), (pos, nor) in self.parts.items():
            m = {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [*color, alpha],
                    "metallicFactor": 0.1,
                    "roughnessFactor": 0.6,
                }
            }
            if glow:
                m["emissiveFactor"] = list(color)
            if alpha < 1:
                m["alphaMode"] = "BLEND"
            materials.append(m)
            prim = {"attributes": {}, "material": len(materials) - 1}
            for name, data in (("POSITION", pos), ("NORMAL", nor)):
                raw = struct.pack(f"<{len(data)}f", *data)
                views.append(
                    {"buffer": 0, "byteOffset": len(blob), "byteLength": len(raw), "target": 34962}
                )
                blob.extend(raw)
                acc = {
                    "bufferView": len(views) - 1,
                    "componentType": 5126,
                    "count": len(data) // 3,
                    "type": "VEC3",
                }
                if name == "POSITION":
                    xs, ys, zs = data[0::3], data[1::3], data[2::3]
                    acc["min"] = [min(xs), min(ys), min(zs)]
                    acc["max"] = [max(xs), max(ys), max(zs)]
                accessors.append(acc)
                prim["attributes"][name] = len(accessors) - 1
            meshes.append({"primitives": [prim]})
        doc = {
            "asset": {"version": "2.0", "generator": "3Drender tools/models3d.py"},
            "scene": 0,
            "scenes": [{"nodes": list(range(len(meshes)))}],
            "nodes": [{"mesh": i} for i in range(len(meshes))],
            "meshes": meshes,
            "materials": materials,
            "accessors": accessors,
            "bufferViews": views,
            "buffers": [{"byteLength": len(blob)}],
        }
        js = json.dumps(doc, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        blob += b"\0" * (-len(blob) % 4)
        total = 12 + 8 + len(js) + 8 + len(blob)
        return (
            struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<I4s", len(js), b"JSON")
            + js
            + struct.pack("<I4s", len(blob), b"BIN\0")
            + bytes(blob)
        )


# ---------------------------------------------------------------- модели
# ширина — по X, глубина — по Z (перед — к −Z), высота — по Y


def couch(pad: Color, w: float = 1.9, d: float = 0.65, h: float = 0.65) -> Model:
    m = Model()
    m.legs(-w / 2 + 0.08, -d / 2 + 0.06, w / 2 - 0.08, d / 2 - 0.06, h - 0.1)
    m.box(-w / 2 + 0.05, h - 0.14, -d / 2 + 0.03, w / 2 - 0.05, h - 0.1, d / 2 - 0.03, STEEL)
    m.box(-w / 2, h - 0.1, -d / 2, w / 2 - 0.55, h, d / 2, pad)
    # приподнятое изголовье справа
    k = (pad, False, 1.0)
    x0, x1, y0, y1 = w / 2 - 0.55, w / 2, h - 0.1, h
    lift = 0.22
    a, b = (x0, y1, -d / 2), (x1, y1 + lift, -d / 2)
    c, e = (x1, y1 + lift, d / 2), (x0, y1, d / 2)
    m.quad(k, a, e, c, b)
    m.quad(k, (x0, y0, -d / 2), (x1, y0, -d / 2), (x1, y0, d / 2), (x0, y0, d / 2))
    m.quad(k, (x0, y0, -d / 2), a, b, (x1, y0, -d / 2))
    m.quad(k, (x0, y0, d / 2), (x1, y0, d / 2), c, e)
    m.quad(k, (x1, y0, -d / 2), b, c, (x1, y0, d / 2))
    return m


def massage_couch() -> Model:
    m = Model()
    w, d, h = 1.9, 0.7, 0.7
    for x in (-w / 2 + 0.15, w / 2 - 0.15):
        m.box(x - 0.03, 0, -d / 2 + 0.05, x + 0.03, h - 0.08, -d / 2 + 0.1, PAD2)
        m.box(x - 0.03, 0, d / 2 - 0.1, x + 0.03, h - 0.08, d / 2 - 0.05, PAD2)
        m.box(x - 0.03, 0.15, -d / 2 + 0.05, x + 0.03, 0.2, d / 2 - 0.05, PAD2)
    m.box(-w / 2, h - 0.08, -d / 2, w / 2, h, d / 2, PAD)
    m.box(w / 2 - 0.3, h - 0.001, -0.06, w / 2 - 0.18, h + 0.002, 0.06, DARK)  # отверстие для лица
    return m


def stretcher() -> Model:
    m = Model()
    w, d, h = 2.0, 0.65, 0.8
    m.legs(-w / 2 + 0.15, -d / 2 + 0.08, w / 2 - 0.15, d / 2 - 0.08, h - 0.12, wheels=True)
    m.box(-w / 2, h - 0.15, -d / 2, w / 2, h - 0.11, d / 2, STEEL)
    m.box(-w / 2 + 0.03, h - 0.11, -d / 2 + 0.03, w / 2 - 0.03, h - 0.02, d / 2 - 0.03, WHITE)
    for z in (-d / 2, d / 2):
        m.box(-w / 2 + 0.3, h - 0.02, z - 0.01, w / 2 - 0.3, h + 0.02, z + 0.01, STEEL)
        m.cyl(-w / 2 + 0.3, h - 0.11, z, 0.01, 0.13, STEEL)
        m.cyl(w / 2 - 0.3, h - 0.11, z, 0.01, 0.13, STEEL)
    m.box(-w / 2 + 0.05, 0.14, -d / 2 + 0.06, w / 2 - 0.05, 0.16, d / 2 - 0.06, GREY)
    return m


def dome_camera(fisheye: bool = False) -> Model:
    m = Model()
    r = 0.06 if fisheye else 0.055
    h = 0.05 if fisheye else 0.085
    base = 0.02 if fisheye else 0.035
    m.cyl(0, h - base, 0, r, base, WHITE)
    m.dome(0, h - base, 0, r * (0.55 if fisheye else 0.85), DARK, alpha=0.9)
    return m


def height_meter() -> Model:
    m = Model()
    m.box(-0.2, 0, -0.2, 0.2, 0.03, 0.2, WHITE)
    m.box(-0.025, 0.03, 0.12, 0.025, 2.1, 0.17, STEEL)
    m.box(-0.12, 1.7, -0.05, 0.12, 1.72, 0.17, WHITE)
    for i in range(20):
        y = 0.1 + i * 0.1
        m.box(-0.026, y, 0.115, 0.0, y + 0.004, 0.12, DARK)
    return m


def chair_row(seats: int = 3, w: float = 1.7, d: float = 0.6, h: float = 0.82) -> Model:
    m = Model()
    m.box(-w / 2, 0.3, -0.03, w / 2, 0.36, 0.03, STEEL)
    for x in (-w / 2 + 0.1, w / 2 - 0.1):
        m.box(x - 0.025, 0, -d / 2 + 0.05, x + 0.025, 0.36, d / 2 - 0.05, STEEL)
        m.box(x - 0.025, 0, -d / 2 + 0.05, x + 0.025, 0.02, d / 2 - 0.05, DARK)
    sw = w / seats
    for i in range(seats):
        x0 = -w / 2 + i * sw + 0.02
        x1 = x0 + sw - 0.04
        m.box(x0, 0.4, -d / 2, x1, 0.46, d / 2 - 0.08, BLUE)
        m.box(x0, 0.46, d / 2 - 0.1, x1, h, d / 2 - 0.04, BLUE)
        m.box((x0 + x1) / 2 - 0.02, 0.36, -0.03, (x0 + x1) / 2 + 0.02, 0.4, 0.2, STEEL)
    return m


def garment_rack() -> Model:
    m = Model()
    w, d, h = 1.5, 0.6, 1.8
    for x in (-w / 2 + 0.03, w / 2 - 0.03):
        m.cyl(x, 0.05, 0, 0.015, h - 0.05, STEEL)
        m.box(x - 0.02, 0, -d / 2, x + 0.02, 0.05, d / 2, STEEL)
    m.cyl(-w / 2, h - 0.03, 0, 0.015, w, STEEL, axis="x")
    m.cyl(-w / 2, 0.15, 0, 0.012, w, STEEL, axis="x")
    for i in range(7):
        x = -w / 2 + 0.25 + i * 0.17
        m.box(x - 0.005, h - 0.45, -0.22, x + 0.005, h - 0.08, 0.22, GREY)
    return m


def ultrasound() -> Model:
    m = Model()
    w, d = 0.55, 0.85
    m.box(-w / 2, 0.06, -d / 2, w / 2, 0.16, d / 2, WHITE)
    for x in (-w / 2 + 0.05, w / 2 - 0.05):
        for z in (-d / 2 + 0.05, d / 2 - 0.05):
            m.cyl(x - 0.02, 0.03, z, 0.03, 0.04, DARK, axis="x")
    m.box(-0.12, 0.16, 0.05, 0.12, 0.7, 0.3, WHITE)  # стойка
    m.box(-w / 2, 0.7, -d / 2 + 0.05, w / 2, 0.85, d / 2 - 0.1, WHITE)  # пульт
    m.box(-w / 2 + 0.05, 0.85, -d / 2 + 0.1, w / 2 - 0.05, 0.86, 0.05, GREY)  # клавиатура
    m.box(-0.03, 0.85, 0.1, 0.03, 1.05, 0.16, GREY)  # кронштейн
    m.box(-0.25, 1.05, 0.05, 0.25, 1.42, 0.1, DARK)  # монитор
    m.box(-0.23, 1.07, 0.049, 0.23, 1.4, 0.05, SCREEN, glow=True)
    m.box(w / 2, 0.75, -0.1, w / 2 + 0.04, 0.82, 0.0, GREY)  # датчик
    return m


def ecg() -> Model:
    m = Model()
    m.box(-0.165, 0, -0.14, 0.165, 0.07, 0.14, WHITE)
    m.box(-0.15, 0.07, -0.12, 0.05, 0.072, 0.02, GREY)  # клавиши
    m.box(0.06, 0.07, -0.12, 0.15, 0.09, 0.0, SCREEN, glow=True)
    m.box(-0.14, 0.07, 0.05, 0.14, 0.09, 0.12, (0.98, 0.95, 0.9))  # лента
    return m


def defibrillator() -> Model:
    m = Model()
    m.box(-0.11, 0, -0.095, 0.11, 0.17, 0.095, ORANGE)
    m.box(-0.08, 0.17, -0.02, 0.08, 0.2, 0.02, DARK)  # ручка
    m.box(-0.07, 0.07, -0.096, 0.03, 0.14, -0.095, SCREEN, glow=True)
    m.cyl(0.06, 0.1, -0.096, 0.018, 0.004, (0.3, 0.75, 0.35), axis="z")
    return m


def wall_light_box(face: Color, chart: bool) -> Model:
    m = Model()
    w, d, h = 0.45, 0.1, 0.55 if not chart else 0.6
    m.box(-w / 2, 0, 0, w / 2, h, d, WHITE)
    m.box(-w / 2 + 0.03, 0.03, -0.001, w / 2 - 0.03, h - 0.03, 0.0, face, glow=True)
    if chart:
        for i in range(8):
            size = 0.05 - i * 0.005
            y = h - 0.08 - i * 0.06
            for j in range(3 + i // 2):
                x = -0.12 + j * (0.24 / (2 + i // 2))
                m.box(x, y, -0.002, x + size * 0.8, y + size * 0.6, -0.001, DARK)
    return m


def aspirator() -> Model:
    m = Model()
    w, d = 0.45, 0.38
    m.box(-w / 2, 0.06, -d / 2, w / 2, 0.5, d / 2, WHITE)
    for x in (-w / 2 + 0.04, w / 2 - 0.04):
        for z in (-d / 2 + 0.04, d / 2 - 0.04):
            m.cyl(x - 0.02, 0.03, z, 0.03, 0.04, DARK, axis="x")
    m.box(-w / 2 + 0.05, 0.3, -d / 2 - 0.001, w / 2 - 0.05, 0.42, -d / 2, GREY)
    for x in (-0.1, 0.1):
        m.cyl(x, 0.5, 0, 0.07, 0.3, GLASS, alpha=0.6)
        m.cyl(x, 0.8, 0, 0.072, 0.03, BLUE)
    m.box(-0.2, 0.84, 0.15, 0.2, 0.85, 0.17, STEEL)
    return m


def steel_table(w: float, d: float, h: float, top: Color = STEEL, rim: bool = False) -> Model:
    m = Model()
    m.legs(-w / 2 + 0.04, -d / 2 + 0.04, w / 2 - 0.04, d / 2 - 0.04, h - 0.03, wheels=True)
    m.box(-w / 2, h - 0.03, -d / 2, w / 2, h, d / 2, top)
    m.box(-w / 2 + 0.02, 0.25, -d / 2 + 0.02, w / 2 - 0.02, 0.27, d / 2 - 0.02, STEEL)
    if rim:
        for z in (-d / 2, d / 2 - 0.015):
            m.box(-w / 2, h, z, w / 2, h + 0.03, z + 0.015, STEEL)
    return m


def changing_table() -> Model:
    m = Model()
    w, d, h = 0.9, 0.8, 0.85
    m.box(-w / 2, 0, -d / 2, w / 2, h - 0.08, d / 2, WHITE)
    for i in range(2):
        y = 0.1 + i * 0.35
        m.box(-w / 2 + 0.03, y, -d / 2 - 0.001, w / 2 - 0.03, y + 0.3, -d / 2, (0.88, 0.9, 0.92))
        m.box(-0.06, y + 0.24, -d / 2 - 0.02, 0.06, y + 0.26, -d / 2, GREY)
    m.box(-w / 2, h - 0.08, -d / 2, w / 2, h - 0.02, d / 2, (0.55, 0.78, 0.86))
    for x0, x1, z0, z1 in (
        (-w / 2, w / 2, d / 2 - 0.04, d / 2),
        (-w / 2, -w / 2 + 0.04, -d / 2, d / 2),
        (w / 2 - 0.04, w / 2, -d / 2, d / 2),
    ):
        m.box(x0, h - 0.02, z0, x1, h + 0.08, z1, WHITE)
    return m


def recirculator() -> Model:
    m = Model()
    m.box(-0.06, 0, 0, 0.06, 0.9, 0.12, WHITE)
    m.box(-0.045, 0.1, -0.001, 0.045, 0.8, 0.0, (0.55, 0.35, 0.9), glow=True)
    m.box(-0.05, 0.84, -0.002, 0.05, 0.86, 0.0, GREY)
    return m


def autorefractor() -> Model:
    m = Model()
    m.box(-0.14, 0, -0.25, 0.14, 0.12, 0.25, WHITE)
    m.box(-0.1, 0.12, -0.05, 0.1, 0.38, 0.2, WHITE)
    m.cyl(0, 0.3, -0.05, 0.035, 0.12, DARK, axis="z")
    m.box(-0.08, 0.2, 0.2, 0.08, 0.32, 0.201, SCREEN, glow=True)
    # подбородник
    m.cyl(-0.1, 0.12, -0.22, 0.008, 0.33, STEEL)
    m.cyl(0.1, 0.12, -0.22, 0.008, 0.33, STEEL)
    m.box(-0.1, 0.3, -0.24, 0.1, 0.31, -0.2, GREY)
    m.box(-0.1, 0.44, -0.23, 0.1, 0.45, -0.21, GREY)
    return m


def sign_projector() -> Model:
    m = Model()
    m.box(-0.125, 0.05, 0.0, 0.125, 0.22, 0.32, WHITE)
    m.cyl(0, 0.14, 0.0, 0.04, -0.05, DARK, axis="z")
    m.box(-0.04, 0, 0.2, 0.04, 0.05, 0.32, GREY)
    return m


def surgical_light() -> Model:
    m = Model()
    for i in range(5):
        t = 2 * math.pi * i / 5
        x, z = 0.3 * math.cos(t), 0.3 * math.sin(t)
        m.box(
            min(0, x) - 0.02,
            0.04,
            min(0, z) - 0.02,
            max(0, x) + 0.02,
            0.07,
            max(0, z) + 0.02,
            STEEL,
        )
        m.cyl(x - 0.02, 0.025, z, 0.025, 0.04, DARK, axis="x")
    m.cyl(0, 0.07, 0, 0.025, 1.45, STEEL)
    m.cyl(0, 1.5, 0, 0.02, 0.4, STEEL, axis="z", r2=0.02)
    m.cyl(0, 1.45, 0.4, 0.02, -0.4, STEEL, axis="z")
    m.cyl(0, 1.5, -0.2, 0.33, 0.12, WHITE, r2=0.2)
    m.cyl(0, 1.499, -0.2, 0.3, 0.001, GLOW, glow=True)
    return m


def gyn_chair() -> Model:
    m = Model()
    m.cyl(0, 0, 0, 0.28, 0.06, GREY, r2=0.24)  # основание
    m.cyl(0, 0.06, 0, 0.07, 0.45, STEEL)  # подъёмник
    m.box(-0.35, 0.5, -0.3, 0.25, 0.62, 0.3, PAD)  # сиденье
    # спинка откинута назад (к +X)
    k = (PAD, False, 1.0)
    a, b = (0.25, 0.62, -0.3), (0.25, 0.62, 0.3)
    c, d = (0.85, 1.05, 0.3), (0.85, 1.05, -0.3)
    m.quad(k, a, b, c, d)
    m.quad(k, (0.25, 0.52, -0.3), (0.85, 0.95, -0.3), (0.85, 0.95, 0.3), (0.25, 0.52, 0.3))
    m.quad(k, a, d, (0.85, 0.95, -0.3), (0.25, 0.52, -0.3))
    m.quad(k, b, (0.25, 0.52, 0.3), (0.85, 0.95, 0.3), c)
    m.quad(k, d, c, (0.85, 0.95, 0.3), (0.85, 0.95, -0.3))
    m.box(0.8, 0.98, -0.12, 0.95, 1.1, 0.12, PAD)  # подголовник
    # подставки для ног (к −X)
    for z in (-0.22, 0.22):
        m.cyl(-0.4, 0.55, z, 0.015, 0.35, STEEL, axis="x", r2=0.015)
        m.cyl(-0.75, 0.55, z, 0.015, 0.3, STEEL)
        m.box(-0.85, 0.85, z - 0.07, -0.65, 0.9, z + 0.07, PAD)
    for z in (-0.32, 0.32):
        m.box(-0.1, 0.62, z - 0.02, 0.2, 0.75, z + 0.02, STEEL)  # поручни
    return m


def panel_light(w: float = 0.595, d: float = 0.595, h: float = 0.04) -> Model:
    m = Model()
    m.box(-w / 2, 0, -d / 2, w / 2, h, d / 2, WHITE)
    m.box(-w / 2 + 0.02, -0.001, -d / 2 + 0.02, w / 2 - 0.02, 0.0, d / 2 - 0.02, GLOW, glow=True)
    return m


def medical_screen() -> Model:
    m = Model()
    w, h = 1.8, 1.7
    panels = 3
    pw = w / panels
    fabric = (0.80, 0.90, 0.86)
    for i in range(panels):
        x0 = -w / 2 + i * pw
        for x in (x0 + 0.01, x0 + pw - 0.01):
            m.cyl(x, 0.08, 0, 0.012, h - 0.08, STEEL)
        m.cyl(x0, h - 0.01, 0, 0.012, pw, STEEL, axis="x")
        m.box(x0 + 0.03, 0.25, -0.004, x0 + pw - 0.03, h - 0.05, 0.004, fabric)
        for x in (x0 + 0.05, x0 + pw - 0.05):
            m.cyl(x - 0.015, 0.03, 0, 0.03, 0.03, DARK, axis="x")
        m.cyl(x0, 0.08, 0, 0.01, pw, STEEL, axis="x")
    return m


MODELS = {
    "Кушетка смотровая": ("kushetka-smotrovaya", lambda: couch(PAD)),
    "Кушетка массажная": ("kushetka-massazhnaya", massage_couch),
    "Каталка медицинская": ("katalka", stretcher),
    "Камера купольная": ("kamera-kupolnaya", lambda: dome_camera()),
    "Камера «рыбий глаз»": ("kamera-rybiy-glaz", lambda: dome_camera(fisheye=True)),
    "Ростомер": ("rostomer", height_meter),
    "Секция стульев трёхместная": ("sektsiya-stulev", chair_row),
    "Вешалка гардеробная": ("veshalka-garderobnaya", garment_rack),
    "Аппарат УЗИ": ("apparat-uzi", ultrasound),
    "Электрокардиограф": ("elektrokardiograf", ecg),
    "Дефибриллятор": ("defibrillyator", defibrillator),
    "Негатоскоп": ("negatoskop", lambda: wall_light_box(GLOW, chart=False)),
    "Аппарат Рота (таблица Сивцева)": ("apparat-rota", lambda: wall_light_box(GLOW, chart=True)),
    "Аспиратор хирургический": ("aspirator", aspirator),
    "Стол инструментальный": ("stol-instrumentalnyy", lambda: steel_table(0.6, 0.4, 0.8, rim=True)),
    "Стол манипуляционный": ("stol-manipulyatsionnyy", lambda: steel_table(0.7, 0.5, 0.85)),
    "Стол перевязочный": ("stol-perevyazochnyy", lambda: steel_table(0.7, 0.5, 0.85, top=WHITE)),
    "Стол пеленальный": ("stol-pelenalnyy", changing_table),
    "Облучатель-рециркулятор": ("obluchatel-retsirkulyator", recirculator),
    "Авторефкератометр": ("avtorefkeratometr", autorefractor),
    "Проектор знаков": ("proektor-znakov", sign_projector),
    "Светильник хирургический передвижной": ("svetilnik-khirurgicheskiy", surgical_light),
    "Кресло гинекологическое": ("kreslo-ginekologicheskoe", gyn_chair),
    "Светильник светодиодный 600×600": ("svetilnik-panel-600", panel_light),
    "Светильник для чистых помещений": (
        "svetilnik-chistye-pomeshcheniya",
        lambda: panel_light(h=0.08),
    ),
    "Ширма медицинская": ("shirma-meditsinskaya", medical_screen),
}

if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for type_name, (slug, build) in MODELS.items():
        data = build().glb()
        (out / f"{slug}.glb").write_bytes(data)
        print(f"{slug}.glb  {len(data) // 1024} КБ  ← {type_name}")
