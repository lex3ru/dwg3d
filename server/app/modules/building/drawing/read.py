"""Чтение чертежа: DWG переводится в DXF (LibreDWG), DXF читается ezdxf; блоки
раскрываются; всё приводится к миллиметрам и простым фигурам."""

import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf import recover
from ezdxf.entities import DXFGraphic

from app.core.errors import AppError

Pt = tuple[float, float]

# что не рисует здание: размеры, выноски, видовые экраны
SKIP = {
    "DIMENSION",
    "ARC_DIMENSION",
    "LARGE_RADIAL_DIMENSION",
    "LEADER",
    "MULTILEADER",
    "MLEADER",
    "VIEWPORT",
    "TOLERANCE",
    "WIPEOUT",
    "IMAGE",
    "OLE2FRAME",
    "POINT",
    "RAY",
    "XLINE",
    "3DFACE",
    "3DSOLID",
    "BODY",
    "REGION",
    "MESH",
}
UNITS = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 14: 100.0}  # $INSUNITS → мм


@dataclass
class Seg:
    layer: str
    a: Pt
    b: Pt
    shape: int = 0  # номер фигуры чертежа: отрезки одной полилинии — одна фигура


@dataclass
class Arc:
    layer: str
    center: Pt
    radius: float
    start: float  # градусы, против часовой
    end: float


@dataclass
class Fill:
    layer: str
    ring: list[Pt]


@dataclass
class Text:
    layer: str
    x: float
    y: float
    height: float
    text: str


@dataclass
class Drawing:
    segs: list[Seg] = field(default_factory=list)
    arcs: list[Arc] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    layers: set[str] = field(default_factory=set)
    unit: float = 1.0  # мм в единице чертежа


def _fix_text(text: str) -> str:
    """Текст UTF-8, прочитанный как cp1252 (DXF без указания кодировки), — обратно."""
    if "Ð" not in text and "Ñ" not in text:
        return text
    try:
        fixed = text.encode("cp1252", errors="surrogateescape").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    return fixed


def dwg2dxf() -> str | None:
    found = os.environ.get("APP_DWG2DXF") or shutil.which("dwg2dxf")
    return found if found and Path(found).exists() else None


def to_dxf(path: Path, workdir: Path) -> Path:
    """DXF как есть; DWG — через LibreDWG."""
    with open(path, "rb") as f:
        head = f.read(6)
    if not head.startswith(b"AC10"):
        return path
    tool = dwg2dxf()
    if tool is None:
        raise AppError(
            "На сервере нет конвертера DWG (LibreDWG) — загрузите чертёж в DXF.",
            code="no_dwg_converter",
        )
    out = workdir / "drawing.dxf"
    env = dict(os.environ)
    lib = Path(tool).resolve().parent.parent / "lib"
    if lib.exists():
        env["LD_LIBRARY_PATH"] = f"{lib}:{env.get('LD_LIBRARY_PATH', '')}"
    result = subprocess.run(
        [tool, "-y", "-o", str(out), str(path)], capture_output=True, timeout=900, env=env
    )
    if not out.exists() or out.stat().st_size == 0:
        tail = result.stderr.decode(errors="replace")[-300:]
        raise AppError(
            f"DWG не читается (версия или повреждение файла): {tail.strip()}", code="bad_dwg"
        )
    return out


def _unit(doc: ezdxf.document.Drawing, extent: float) -> float:
    code = doc.header.get("$INSUNITS", 0)
    if code in UNITS:
        return UNITS[code]
    # единицы не указаны: здание в метрах занимает десятки единиц, в мм — десятки тысяч
    return 1000.0 if 0 < extent < 2000 else 1.0


def _walk(entities, depth: int = 0, parent: str | None = None):  # type: ignore[no-untyped-def]
    for e in entities:
        t = e.dxftype()
        if t in SKIP:
            continue
        # фигура блока на слое «0» рисуется на слое вставки — как в AutoCAD
        if parent is not None and e.dxf.get("layer", "0") == "0":
            e.dxf.layer = parent
        if t == "INSERT":
            if depth < 8:
                layer = e.dxf.get("layer", "0")
                try:
                    yield from _walk(e.virtual_entities(), depth + 1, layer)
                except Exception:  # битый блок — пропускаем, как пропустил бы AutoCAD
                    pass
                yield from getattr(e, "attribs", [])
            continue
        yield e


def load(path: Path) -> Drawing:
    with tempfile.TemporaryDirectory() as tmp:
        dxf = to_dxf(path, Path(tmp))
        try:
            doc, _auditor = recover.readfile(str(dxf))
        except Exception as e:
            raise AppError(f"Файл не читается как DXF: {e}", code="bad_dxf") from e
    drawing = Drawing()
    raw: list[DXFGraphic] = list(_walk(doc.modelspace()))
    xs = []
    for e in raw[:2000]:
        if e.dxftype() == "LINE":
            xs += [e.dxf.start.x, e.dxf.end.x]
    extent = (max(xs) - min(xs)) if xs else 0
    k = _unit(doc, extent)
    drawing.unit = k

    def pt(v) -> Pt:  # type: ignore[no-untyped-def]
        return (float(v[0]) * k, float(v[1]) * k)

    for shape, e in enumerate(raw):
        t = e.dxftype()
        layer = e.dxf.get("layer", "0")
        drawing.layers.add(layer)
        try:
            if t == "LINE":
                a, b = pt(e.dxf.start), pt(e.dxf.end)
                if a != b:
                    drawing.segs.append(Seg(layer, a, b, shape))
            elif t in ("LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"):
                points = (
                    [pt(p) for p in e.flattening(5 / k if k else 5)]
                    if t != "LWPOLYLINE"
                    else _lw_points(e, k)
                )
                if (
                    t in ("LWPOLYLINE", "POLYLINE")
                    and e.is_closed
                    and points
                    and points[0] != points[-1]
                ):
                    points.append(points[0])
                drawing.segs += [
                    Seg(layer, a, b, shape)
                    for a, b in zip(points, points[1:], strict=False)
                    if a != b
                ]
            elif t == "ARC":
                c = pt(e.dxf.center)
                r = e.dxf.radius * k
                drawing.arcs.append(
                    Arc(layer, c, r, e.dxf.start_angle % 360, e.dxf.end_angle % 360)
                )
                points = [pt(p) for p in e.flattening(max(r / 50, 5) / k)]
                drawing.segs += [
                    Seg(layer, a, b, shape)
                    for a, b in zip(points, points[1:], strict=False)
                    if a != b
                ]
            elif t == "CIRCLE":
                c, r = pt(e.dxf.center), e.dxf.radius * k
                ring = [
                    (c[0] + r * math.cos(i * math.tau / 16), c[1] + r * math.sin(i * math.tau / 16))
                    for i in range(17)
                ]
                drawing.segs += [
                    Seg(layer, a, b, shape) for a, b in zip(ring, ring[1:], strict=False)
                ]
            elif t == "HATCH":
                for ring in _hatch_rings(e, k):
                    drawing.fills.append(Fill(layer, ring))
            elif t in ("TEXT", "ATTRIB"):
                text = e.plain_text() if hasattr(e, "plain_text") else e.dxf.text
                if text and text.strip():
                    p = pt(e.dxf.insert)
                    drawing.texts.append(
                        Text(layer, p[0], p[1], e.dxf.get("height", 250) * k,
                             _fix_text(text.strip()))
                    )
            elif t == "MTEXT":
                text = e.plain_text()
                if text and text.strip():
                    p = pt(e.dxf.insert)
                    drawing.texts.append(
                        Text(layer, p[0], p[1], e.dxf.get("char_height", 250) * k,
                             _fix_text(text.strip()))
                    )
        except Exception:  # одна испорченная фигура не мешает остальным
            continue
    return drawing


def _lw_points(e, k: float) -> list[Pt]:  # type: ignore[no-untyped-def]
    pts = list(e.get_points("xyb"))
    if not pts:
        return []
    out: list[Pt] = []
    n = len(pts)
    last = n if e.closed else n - 1
    for i in range(last):
        x0, y0, bulge = pts[i]
        x1, y1, _ = pts[(i + 1) % n]
        out.append((x0 * k, y0 * k))
        if abs(bulge) > 1e-9:
            from app.modules.building.geometry import arc_points

            arc = arc_points((x0 * k, y0 * k), (x1 * k, y1 * k), bulge, 150)
            out += arc[1:-1]
    x, y, _ = pts[last % n] if not e.closed else pts[0]
    out.append((x * k, y * k))
    return out


def _hatch_rings(e, k: float) -> list[list[Pt]]:  # type: ignore[no-untyped-def]
    rings = []
    for path in e.paths:
        try:
            if hasattr(path, "vertices") and path.vertices:
                ring = [(v[0] * k, v[1] * k) for v in path.vertices]
            else:
                ring = []
                for edge in path.edges:
                    if hasattr(edge, "start") and hasattr(edge, "end") and edge.type.name == "LINE":
                        ring.append((edge.start[0] * k, edge.start[1] * k))
                    elif hasattr(edge, "construction_tool"):
                        tool = edge.construction_tool()
                        ring += [(p[0] * k, p[1] * k) for p in tool.flattening(5 / k)]
            if len(ring) >= 3:
                rings.append(ring)
        except Exception:
            continue
    return rings
