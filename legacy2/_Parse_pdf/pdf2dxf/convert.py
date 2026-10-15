"""PDF page -> DXF document."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
import pymupdf
from ezdxf import colors as dxfcolors
from ezdxf import units
from ezdxf.document import Drawing
from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS

from .geometry import (
    Point,
    Seg,
    arc_angles,
    bezier_to_seg,
    dist,
    flatten_bezier,
    is_full_circle,
    join_chains,
)

PT_MM = 25.4 / 72.0
TEXT_CAP_RATIO = 0.72  # DXF text height is cap height, PDF font size is the em height


@dataclass
class Options:
    scale: float = 1.0          # drawing scale denominator: 100 means 1:100 (paper mm -> model mm)
    mode: str = "auto"          # auto | vector | raster
    fills: bool = True
    text: bool = True
    lineweights: bool = True
    tol: float = 0.02           # arc-fit tolerance, paper mm
    dpi: int = 300              # raster mode: rendering resolution
    min_len: float = 1.0        # raster mode: drop traces shorter than this, paper mm
    simplify: float = 0.4       # raster mode: polyline simplification, paper mm
    drop_frame: bool = False    # remove the sheet border (long lines along the page edges)
    stroke_layer: str | None = None  # put every stroke on this layer (e.g. "A-WALL")
    fill_layer: str | None = None    # put every fill on this layer (e.g. "Штриховка")


@dataclass
class Report:
    page: int
    mode: str = "vector"
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def count(self, kind: str, n: int = 1) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + n


_ACI_RGB = [
    ((c >> 16) & 255, (c >> 8) & 255, c & 255) for c in dxfcolors.DXF_DEFAULT_COLORS
]
_BAD_LAYER_CHARS = re.compile(r'[<>/\\":;?*|=`,]')


def nearest_aci(rgb: tuple[int, int, int]) -> int:
    if rgb == (0, 0, 0):
        return 7
    return min(
        range(1, 256),
        key=lambda i: sum((a - b) ** 2 for a, b in zip(_ACI_RGB[i], rgb)),
    )


def to_rgb(c) -> tuple[int, int, int] | None:
    if c is None:
        return None
    if len(c) == 1:
        c = (c[0],) * 3
    return tuple(max(0, min(255, round(v * 255))) for v in c[:3])  # type: ignore[return-value]


def snap_lineweight(width_pt: float) -> int:
    hundredths = width_pt * PT_MM * 100.0
    return min((w for w in VALID_DXF_LINEWEIGHTS if w > 0), key=lambda w: abs(w - hundredths))


class Writer:
    """Collects entities of one page into a DXF document."""

    def __init__(self, opts: Options, report: Report):
        self.opts = opts
        self.report = report
        self.doc: Drawing = ezdxf.new("R2010", setup=True)
        self.doc.units = units.MM
        self.doc.header["$LWDISPLAY"] = 1
        self.msp = self.doc.modelspace()
        self.k = PT_MM * opts.scale  # PDF points -> DXF units
        self.tol = opts.tol * opts.scale
        self._linetypes: dict[str, str] = {}
        # stroke chains waiting to be joined across PDF paths, grouped by drawing style
        self._pending: dict[tuple, list[list[Seg]]] = {}
        if opts.text:
            self.doc.styles.add("PDF_TEXT", font="arial.ttf")

    # -- layers / linetypes -------------------------------------------------
    def layer(self, rgb: tuple[int, int, int] | None, prefix: str, oc_name: str | None = None,
              force: str | None = None) -> str:
        rgb = rgb or (0, 0, 0)
        oc_name = force or oc_name
        name = _BAD_LAYER_CHARS.sub("_", oc_name).strip() if oc_name else f"{prefix}_{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        name = name[:255] or prefix
        if name not in self.doc.layers:
            self.doc.layers.add(
                name,
                color=nearest_aci(rgb),
                true_color=dxfcolors.rgb2int(rgb),
            )
        return name

    def linetype(self, dashes: str | None) -> str | None:
        if not dashes:
            return None
        nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+", dashes.split("]")[0])]
        nums = [n for n in nums if n > 0]
        if not nums:
            return None
        if len(nums) % 2:
            nums *= 2
        pattern = [n * self.k for n in nums]
        key = ",".join(f"{n:.4f}" for n in pattern)
        if key not in self._linetypes:
            name = f"PDF_DASH_{len(self._linetypes) + 1}"
            flat = [sum(pattern)]
            for i, n in enumerate(pattern):
                flat.append(n if i % 2 == 0 else -n)
            self.doc.linetypes.add(name, pattern=flat, description=f"pdf dash {dashes}")
            self._linetypes[key] = name
        return self._linetypes[key]

    # -- entities -----------------------------------------------------------
    def emit_chain(self, chain: list[Seg], attribs: dict, close: bool) -> None:
        """Write a connected chain of segments as the simplest fitting DXF entity."""
        if not chain:
            return
        tol = self.tol
        closed = close or dist(chain[0].p0, chain[-1].p1) < tol
        if len(chain) == 1 and not (closed and chain[0].bulge):
            s = chain[0]
            if s.bulge == 0:
                if dist(s.p0, s.p1) > 1e-9:
                    self.msp.add_line(s.p0, s.p1, dxfattribs=attribs)
                    self.report.count("LINE")
            else:
                a0, a1 = arc_angles(s)
                self.msp.add_arc(s.center, s.radius, a0, a1, dxfattribs=attribs)
                self.report.count("ARC")
            return
        if closed:
            circle = is_full_circle(chain, tol * 2)
            if circle:
                self.msp.add_circle(circle[0], circle[1], dxfattribs=attribs)
                self.report.count("CIRCLE")
                return
        pts = [(s.p0[0], s.p0[1], s.bulge) for s in chain]
        if not closed:
            pts.append((chain[-1].p1[0], chain[-1].p1[1], 0.0))
        self.msp.add_lwpolyline(pts, format="xyb", close=closed, dxfattribs=attribs)
        self.report.count("LWPOLYLINE")

    def add_chain(self, chain: list[Seg], attribs: dict, closed: bool) -> None:
        """Queue a stroke chain; flush_chains() joins touching ones and writes them."""
        if closed or dist(chain[0].p0, chain[-1].p1) < self.tol:
            self.emit_chain(chain, attribs, True)
            return
        if len(chain) == 1 and chain[0].bulge == 0 and dist(chain[0].p0, chain[0].p1) < 1e-9:
            return
        self._pending.setdefault(tuple(sorted(attribs.items())), []).append(chain)

    def flush_chains(self) -> None:
        for style, chains in self._pending.items():
            attribs = dict(style)
            for chain, closed in join_chains(_dedupe(chains, self.tol), self.tol):
                self.emit_chain(chain, attribs, closed)
        self._pending.clear()

    def emit_spline(self, pts: list[Point], attribs: dict) -> None:
        self.msp.add_open_spline(pts, degree=3, dxfattribs=attribs)
        self.report.count("SPLINE")

    def emit_hatch(self, chains: list[list[Seg]], rgb: tuple[int, int, int], layer: str, even_odd: bool) -> None:
        paths = []
        for chain in chains:
            if len(chain) < 2 and not any(s.bulge for s in chain):
                continue
            verts = [(s.p0[0], s.p0[1], s.bulge) for s in chain]
            if len(verts) >= 2 or any(v[2] for v in verts):
                paths.append(verts)
        if not paths:
            return
        hatch = self.msp.add_hatch(color=7, dxfattribs={"layer": layer, "color": 256})
        hatch.dxf.hatch_style = 0 if even_odd else 1
        hatch.set_solid_fill(color=nearest_aci(rgb), rgb=dxfcolors.RGB(*rgb))
        for verts in paths:
            hatch.paths.add_polyline_path(verts, is_closed=True)
        self.report.count("HATCH")


def _is_white(rgb: tuple[int, int, int]) -> bool:
    return min(rgb) >= 250


def convert_vector_page(page: pymupdf.Page, writer: Writer) -> None:
    opts = writer.opts
    k = writer.k
    rect = page.rect
    rot = page.rotation_matrix

    def tp(p) -> Point:
        # PDF user space is unrotated; rect / rotation_matrix describe the page as displayed
        q = pymupdf.Point(p) * rot
        return (q.x * k, (rect.height - q.y) * k)

    tol = writer.tol
    page_area = rect.width * rect.height

    for d in page.get_drawings():
        kind = d.get("type", "s")
        stroke = to_rgb(d.get("color")) if "s" in kind else None
        fill = to_rgb(d.get("fill")) if "f" in kind and opts.fills else None
        if fill and (_is_white(fill) or _covers_page(d, page_area)):
            fill = None
        if stroke and _is_white(stroke):
            stroke = None  # invisible on white paper
        if stroke and opts.drop_frame and _is_frame(d, rect):
            stroke = None
        if stroke is None and fill is None:
            continue
        oc = d.get("layer")
        attribs: dict = {"layer": writer.layer(stroke, "C", oc, opts.stroke_layer)}
        lt = writer.linetype(d.get("dashes"))
        if lt:
            attribs["linetype"] = lt
        width = d.get("width") or 0
        if opts.lineweights and width and width > 0:
            attribs["lineweight"] = snap_lineweight(width)

        chains: list[list[Seg]] = []
        chain: list[Seg] = []
        splines: list[list[Point]] = []

        def flush() -> None:
            nonlocal chain
            if chain:
                chains.append(chain)
            chain = []

        def add(seg: Seg) -> None:
            if chain and dist(chain[-1].p1, seg.p0) > tol:
                flush()
            chain.append(seg)

        for item in d["items"]:
            op = item[0]
            if op == "l":
                add(Seg(tp(item[1]), tp(item[2])))
            elif op == "c":
                p0, p1, p2, p3 = (tp(p) for p in item[1:5])
                seg = bezier_to_seg(p0, p1, p2, p3, tol)
                if seg:
                    add(seg)
                else:
                    splines.append([p0, p1, p2, p3])
                    flush()
            elif op == "re":
                r = item[1]
                corners = [tp((r.x0, r.y0)), tp((r.x1, r.y0)), tp((r.x1, r.y1)), tp((r.x0, r.y1))]
                flush()
                chains.append([Seg(corners[i], corners[(i + 1) % 4]) for i in range(4)])
            elif op == "qu":
                q = item[1]
                corners = [tp(q.ul), tp(q.ur), tp(q.lr), tp(q.ll)]
                flush()
                chains.append([Seg(corners[i], corners[(i + 1) % 4]) for i in range(4)])
        flush()

        closed_flag = bool(d.get("closePath"))
        if stroke is not None:
            for ch in chains:
                writer.add_chain(ch, attribs, closed_flag and ch is chains[-1])
            for sp in splines:
                writer.emit_spline(sp, attribs)
        if fill is not None:
            hl = writer.layer(fill, "F", None, opts.fill_layer)
            # a curve that cannot become an arc is flattened for the hatch boundary
            fchains = list(chains)
            for sp in splines:
                pts = flatten_bezier(*sp, tol)
                fchains.append([Seg(pts[i], pts[i + 1]) for i in range(len(pts) - 1)])
            writer.emit_hatch(fchains, fill, hl, bool(d.get("even_odd")))

    writer.flush_chains()
    if opts.text:
        convert_text(page, writer)


def _dedupe(chains: list[list[Seg]], tol: float) -> list[list[Seg]]:
    """Drop repeated single straight lines (CAD exports often draw them twice)."""
    seen: set = set()
    out = []
    for c in chains:
        if len(c) == 1 and c[0].bulge == 0:
            a = (round(c[0].p0[0] / tol), round(c[0].p0[1] / tol))
            b = (round(c[0].p1[0] / tol), round(c[0].p1[1] / tol))
            k = (a, b) if a <= b else (b, a)
            if k in seen:
                continue
            seen.add(k)
        out.append(c)
    return out


def _is_frame(d: dict, page: pymupdf.Rect) -> bool:
    """A single line running along most of a page side, or a box about the page size."""
    r = d.get("rect")
    if not r:
        return False
    long_w, long_h = r.width >= 0.85 * page.width, r.height >= 0.85 * page.height
    thin_w, thin_h = r.width <= 1.0, r.height <= 1.0
    return (long_w and long_h) or (long_w and thin_h) or (long_h and thin_w)


def _covers_page(d: dict, page_area: float) -> bool:
    r = d.get("rect")
    return bool(r) and page_area > 0 and r.width * r.height >= 0.95 * page_area


def convert_text(page: pymupdf.Page, writer: Writer) -> None:
    k = writer.k
    rect = page.rect
    rot = page.rotation_matrix
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            d = pymupdf.Point(line["dir"]) * pymupdf.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
            angle = math.degrees(math.atan2(-d.y, d.x))
            for span in line["spans"]:
                txt = span["text"].strip()
                if not txt:
                    continue
                o = pymupdf.Point(span["origin"]) * rot
                x = o.x * k
                y = (rect.height - o.y) * k
                attribs = {
                    "layer": writer.layer(None, "TEXT", "TEXT"),
                    "style": "PDF_TEXT",
                    "height": max(span["size"] * k * TEXT_CAP_RATIO, 1e-3),
                    "rotation": angle,
                    "insert": (x, y),
                }
                rgb = to_rgb([((span["color"] >> s) & 255) / 255 for s in (16, 8, 0)])
                if rgb and rgb != (0, 0, 0):
                    attribs["true_color"] = dxfcolors.rgb2int(rgb)
                writer.msp.add_text(txt, dxfattribs=attribs)
                writer.report.count("TEXT")


def page_is_vector(page: pymupdf.Page, few_paths: int = 10) -> bool:
    """Vector unless the page is essentially a picture (scan) with next to no paths."""
    n = len(page.get_drawings())
    if n == 0:
        return not page.get_image_info()
    if n >= few_paths:
        return True
    area = page.rect.width * page.rect.height
    covered = sum(pymupdf.Rect(i["bbox"]).intersect(page.rect).get_area() for i in page.get_image_info())
    return covered < 0.5 * area


def parse_pages(spec: str, total: int) -> list[int]:
    """'1,3-5' / 'all' -> zero-based page indexes."""
    if spec.strip().lower() == "all":
        return list(range(total))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        lo, hi = int(a), int(b or a)
        if lo < 1 or hi > total or lo > hi:
            raise ValueError(f"страницы {part!r} нет в файле (всего страниц: {total})")
        out.extend(range(lo - 1, hi))
    return out


def convert_page(page: pymupdf.Page, opts: Options, number: int) -> tuple[Drawing, Report]:
    report = Report(page=number)
    writer = Writer(opts, report)
    mode = opts.mode
    if mode == "auto":
        mode = "vector" if page_is_vector(page) else "raster"
    report.mode = mode
    if mode == "vector":
        convert_vector_page(page, writer)
        if not report.counts and not opts.text:
            report.warnings.append("на странице нет векторной графики")
    else:
        from .raster import convert_raster_page

        convert_raster_page(page, writer)
    if not report.counts:
        report.warnings.append("в DXF ничего не попало: страница пустая или режим выбран неверно")
    return writer.doc, report


def convert_pdf(src: Path, dst: Path, pages: str = "1", opts: Options | None = None) -> list[tuple[Path, Report]]:
    opts = opts or Options()
    results = []
    with pymupdf.open(src) as pdf:
        idx = parse_pages(pages, len(pdf))
        for i in idx:
            doc, report = convert_page(pdf[i], opts, i + 1)
            out = dst if len(idx) == 1 else dst.with_name(f"{dst.stem}_p{i + 1}{dst.suffix}")
            doc.saveas(out)
            results.append((out, report))
    return results
