"""DXF reading: flatten all entities (incl. nested blocks) into typed primitives.

All coordinates are converted to meters here, so the rest of the pipeline
works in a single unit system.
"""
from __future__ import annotations

import collections
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import ezdxf
from ezdxf import recover
from ezdxf.path import from_hatch, make_path

from .config import LayerMapper
from .units import resolve_scale

log = logging.getLogger(__name__)

CURVE_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
SOLID_TYPES = {"SOLID", "TRACE"}
MAX_DEPTH = 8


@dataclass
class Shape:
    layer: str
    role: str | None
    pts: np.ndarray            # (N, 2) meters
    closed: bool
    kind: str                  # source dxftype
    space: str = "Model"
    owner: str | None = None   # handle of the top-level floor block, if any
    arc: tuple | None = None   # ARC: (cx, cy, r, start_deg, end_deg), meters

    @property
    def center(self):
        return self.pts.mean(axis=0)


@dataclass
class Text:
    text: str
    x: float
    y: float
    layer: str
    height: float
    space: str = "Model"
    owner: str | None = None


@dataclass
class Insert:
    role: str                  # doors | windows
    block: str
    layer: str
    x: float
    y: float
    rotation: float            # degrees
    pts: np.ndarray            # footprint points (meters)
    attribs: dict
    space: str = "Model"
    owner: str | None = None


@dataclass
class Bubble:                  # grid axis marker (circle + label)
    label: str
    x: float
    y: float
    r: float
    space: str = "Model"
    owner: str | None = None


@dataclass
class Viewport:
    layout: str
    bbox: tuple[float, float, float, float]   # model-space window, meters


@dataclass
class FloorBlock:
    handle: str
    block: str
    layer: str
    attribs: dict
    space: str = "Model"


@dataclass
class Drawing:
    path: str
    scale: float                       # drawing units -> meters
    units: str
    units_source: str
    shapes: list[Shape] = field(default_factory=list)
    texts: list[Text] = field(default_factory=list)
    inserts: list[Insert] = field(default_factory=list)
    bubbles: list[Bubble] = field(default_factory=list)
    viewports: list[Viewport] = field(default_factory=list)
    floor_blocks: list[FloorBlock] = field(default_factory=list)
    layouts: dict[str, int] = field(default_factory=dict)   # layout -> entity count
    layer_stats: dict[str, dict] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "units": self.units, "units_source": self.units_source, "scale": self.scale,
            "shapes": len(self.shapes), "texts": len(self.texts),
            "inserts": len(self.inserts), "grid_bubbles": len(self.bubbles),
            "layouts": self.layouts,
        }


def read_doc(path: Path):
    try:
        return ezdxf.readfile(str(path))
    except Exception:  # damaged / non-standard DXF (common for converted files)
        doc, auditor = recover.readfile(str(path))
        log.info("DXF recovered with %d fixes", len(auditor.fixes))
        return doc


def _plain(e) -> str:
    try:
        if e.dxftype() == "MTEXT":
            return e.plain_text().strip()
        return (e.plain_text() if hasattr(e, "plain_text") else e.dxf.text).strip()
    except Exception:
        return str(e.dxf.get("text", "")).strip()


class _Extractor:
    def __init__(self, doc, mapper: LayerMapper, scale: float, arc_tol: float, floors_mode: str):
        self.doc = doc
        self.m = mapper
        self.s = scale
        self.flat = max(arc_tol / scale, 1e-9)   # flattening sagitta in drawing units
        self.floor_blocks_enabled = floors_mode in ("auto", "blocks")
        self.d: Drawing | None = None
        self.stats = collections.defaultdict(lambda: collections.Counter())

    # -- helpers ---------------------------------------------------------
    def _xy(self, pts) -> np.ndarray:
        a = np.asarray([(p[0], p[1]) for p in pts], dtype=float) * self.s
        return a

    def _paths_pts(self, e):
        """Yield (points, closed) for a curve-like entity."""
        t = e.dxftype()
        if t == "HATCH" or t == "MPOLYGON":
            for p in from_hatch(e):
                pts = list(p.flattening(self.flat))
                if len(pts) >= 3:
                    yield pts, True
            return
        if t in SOLID_TYPES:
            v = [e.dxf.vtx0, e.dxf.vtx1, e.dxf.vtx3, e.dxf.vtx2]
            yield v, True
            return
        if t == "POLYLINE" and not e.is_2d_polyline:
            return  # 3D meshes / polyface: not plan linework
        p = make_path(e)
        pts = list(p.flattening(self.flat))
        if len(pts) < 2:
            return
        closed = t == "CIRCLE" or (t == "ELLIPSE" and abs(e.dxf.end_param - e.dxf.start_param) >= 2 * math.pi - 1e-6)
        if t in ("LWPOLYLINE", "POLYLINE"):
            closed = bool(e.closed) or (len(pts) > 2 and pts[0].isclose(pts[-1]))
        yield pts, closed

    def _footprint(self, insert, depth=0) -> list:
        pts = []
        try:
            for ve in insert.virtual_entities():
                t = ve.dxftype()
                if t == "INSERT" and depth < MAX_DEPTH:
                    pts += self._footprint(ve, depth + 1)
                elif t in CURVE_TYPES:
                    try:
                        pts += [(v.x, v.y) for v in make_path(ve).flattening(self.flat * 4)]
                    except Exception:
                        pass
        except Exception:
            pass
        return pts

    def _attribs(self, insert) -> dict:
        try:
            return {a.dxf.tag: a.dxf.text for a in insert.attribs}
        except Exception:
            return {}

    # -- main walk -------------------------------------------------------
    def walk(self, entities, space: str, owner: str | None, depth: int, parent_layer: str | None):
        d = self.d
        for e in entities:
            try:
                layer = e.dxf.get("layer", "0")
            except Exception:
                continue
            if layer == "0" and parent_layer:
                layer = parent_layer          # layer "0" inside blocks inherits
            t = e.dxftype()
            lrole = self.m.layer_role(layer)
            self.stats[layer][t] += 1
            try:
                if t == "INSERT":
                    self._insert(e, layer, lrole, space, owner, depth)
                elif t in ("TEXT", "MTEXT", "ATTRIB"):
                    txt = _plain(e)
                    if txt:
                        ins = e.dxf.insert
                        h = e.dxf.get("char_height" if t == "MTEXT" else "height", 0) or 0
                        d.texts.append(Text(txt, ins.x * self.s, ins.y * self.s, layer, h * self.s, space, owner))
                elif lrole == "ignore" or t == "DIMENSION":
                    continue
                elif t == "VIEWPORT":
                    continue
                elif t in CURVE_TYPES or t in SOLID_TYPES or t == "HATCH":
                    if t in ("HATCH",) + tuple(SOLID_TYPES) and lrole not in ("walls", "columns", "rooms", "insulation"):
                        continue  # fills only matter as wall/column/room outlines
                    arc = None
                    if t == "ARC":
                        c = e.dxf.center
                        arc = (c.x * self.s, c.y * self.s, e.dxf.radius * self.s,
                               float(e.dxf.start_angle), float(e.dxf.end_angle))
                    for pts, closed in self._paths_pts(e):
                        xy = self._xy(pts)
                        if len(xy) >= 2:
                            d.shapes.append(Shape(layer, lrole, xy, closed, t, space, owner, arc))
                elif t == "MLINE":
                    self.walk(list(e.virtual_entities()), space, owner, depth + 1, layer)
            except Exception as ex:   # never let one bad entity kill the import
                log.debug("skip %s %s: %s", t, layer, ex)

    def _insert(self, e, layer, lrole, space, owner, depth):
        d = self.d
        name = e.dxf.name
        if lrole == "ignore":
            return
        if e.mcount > 1:  # MINSERT arrays
            for sub in e.multi_insert():
                self._insert(sub, layer, lrole, space, owner, depth)
            return
        brole = self.m.block_role(name)
        role = brole or (lrole if lrole in ("doors", "windows", "grid") else None)
        attribs = self._attribs(e)
        ins = e.dxf.insert

        if depth == 0 and owner is None and self.floor_blocks_enabled and self.m.is_floor_block(name):
            owner = e.dxf.handle
            d.floor_blocks.append(FloorBlock(owner, name, layer, attribs, space))

        if role in ("doors", "windows"):
            fp = self._footprint(e)
            if not fp:
                fp = [(ins.x, ins.y)]
            d.inserts.append(Insert(role, name, layer, ins.x * self.s, ins.y * self.s,
                                    float(e.dxf.get("rotation", 0.0)), self._xy(fp), attribs, space, owner))
            return
        if role == "grid":
            circles = [v for v in e.virtual_entities() if v.dxftype() == "CIRCLE"]
            label = next(iter(attribs.values()), "") if attribs else ""
            if not label:
                label = next((_plain(v) for v in e.virtual_entities() if v.dxftype() in ("TEXT", "MTEXT")), "")
            if circles:
                c = circles[0]
                d.bubbles.append(Bubble(label.strip(), c.dxf.center.x * self.s, c.dxf.center.y * self.s,
                                        c.dxf.radius * self.s, space, owner))
            else:
                d.bubbles.append(Bubble(label.strip(), ins.x * self.s, ins.y * self.s, 0.0, space, owner))
            # axis lines inside the bubble block (if any) are handled as grid shapes
            self.walk([v for v in e.virtual_entities() if v.dxftype() in ("LINE", "LWPOLYLINE")],
                      space, owner, depth + 1, layer)
            return
        for tag, val in attribs.items():
            if val.strip():
                d.texts.append(Text(val.strip(), ins.x * self.s, ins.y * self.s, layer, 0.0, space, owner))
        if depth >= MAX_DEPTH:
            return
        try:
            ves = list(e.virtual_entities())
        except Exception:
            return
        self.walk([v for v in ves if v.dxftype() != "ATTRIB"], space, owner, depth + 1, layer)

    def viewports(self):
        for layout in self.doc.layouts:
            if layout.is_modelspace:
                continue
            try:
                main = layout.main_viewport()
                main_h = main.dxf.handle if main else None
            except Exception:
                main_h = None
            for vp in layout.query("VIEWPORT"):
                dx = vp.dxf
                if dx.handle == main_h:
                    continue
                vh = dx.get("view_height", 0)
                if not vh or not dx.height:
                    continue
                tgt = dx.get("view_target_point", (0, 0, 0))
                vc = dx.view_center_point
                cx, cy = (vc[0] + tgt[0]), (vc[1] + tgt[1])
                # skip the paperspace "overall" viewport (shows paper itself)
                if abs(vh - dx.height) < 1e-6 and abs(vc[0] - dx.center[0]) < 1e-6 and not any(tgt):
                    continue
                w = vh * dx.width / dx.height
                s = self.s
                self.d.viewports.append(Viewport(layout.name, ((cx - w / 2) * s, (cy - vh / 2) * s,
                                                              (cx + w / 2) * s, (cy + vh / 2) * s)))


def read_drawing(dxf_path: Path, cfg: dict, doc=None) -> Drawing:
    doc = doc or read_doc(dxf_path)
    mapper = LayerMapper(cfg)
    scale, units, source = resolve_scale(doc, cfg.get("units", "auto"), mapper)
    d = Drawing(str(dxf_path), scale, units, source)
    ex = _Extractor(doc, mapper, scale, cfg["geometry"]["arc_tolerance"], cfg["floors"]["mode"])
    ex.d = d
    ex.walk(doc.modelspace(), "Model", None, 0, None)
    d.layouts["Model"] = len(doc.modelspace())
    for layout in doc.layouts:
        if layout.is_modelspace:
            continue
        d.layouts[layout.name] = len(layout)
        ex.walk([e for e in layout if e.dxftype() != "VIEWPORT"], layout.name, None, 0, None)
    ex.viewports()
    d.layer_stats = {
        name: {"role": mapper.layer_role(name), "count": sum(c.values()), "types": dict(c)}
        for name, c in sorted(ex.stats.items())
    }
    for lay in doc.layers:
        n = lay.dxf.name
        if n not in d.layer_stats:
            d.layer_stats[n] = {"role": mapper.layer_role(n), "count": 0, "types": {}}
    return d
