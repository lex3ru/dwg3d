"""Write the 2D-editor corrections back into the source drawing (DXF/DWG).

Edits are stored in plan coordinates (meters, floors aligned); here they are
mapped back to each sheet's drawing coordinates and applied to the original
DXF:

* erased areas / new openings: wall linework inside is trimmed, jamb lines
  are drawn at the cut
* new walls: closed outlines
* new/changed openings: old door/window symbols removed, a standard symbol
  drawn (window: face lines + glass line; door: leaf + 90° swing arc)
* "fill with wall": the two wall face lines across the gap
* renamed rooms: the room's label text is replaced (or a new one added)

New entities go to dedicated layers whose names match the default layer
mapping, so a re-uploaded file is recognised the same way.
Entities inside block definitions are never modified.
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path

import numpy as np
from ezdxf.enums import TextEntityAlignment
from ezdxf.path import make_path
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

from .config import LayerMapper, load_config
from .convert import ConversionError, find_libredwg, find_oda
from .extract import read_doc, read_drawing
from .floors import align_floors, apply_manual, detect_candidates, parse_mark, resolve_stack
from .geometry import FloorPlan, Opening, _polys, build_plan

log = logging.getLogger(__name__)

EDIT_LAYERS = {   # name, ACI color
    "walls": ("Стены_правки", 1),
    "windows": ("Окна_правки", 5),
    "vitrage": ("Витражи_правки", 4),
    "doors": ("Двери_правки", 30),
    "text": ("Текст_правки", 3),
}
CURVES = ("LINE", "LWPOLYLINE", "POLYLINE", "ARC")
_RE_NUMERIC = re.compile(r"^[\d\s.,+\-±×x*/=()мм²m2]*$", re.I)


def has_edits(cfg: dict) -> bool:
    return any(any(v for v in (e or {}).values()) for e in (cfg.get("edits") or {}).values())


class _FloorWriter:
    def __init__(self, doc, layout, floor, scale: float, mapper: LayerMapper, stats: dict):
        self.doc, self.layout, self.m, self.stats = doc, layout, mapper, stats
        ox, oy = floor.offset
        s = scale
        self.s = s
        # plan (m, aligned) -> drawing units, and back
        self.to_dwg = [1 / s, 0, 0, 1 / s, -ox / s, -oy / s]
        self.to_plan = [s, 0, 0, s, ox, oy]
        self.flat = 0.01 / s

    # ---- helpers -------------------------------------------------------
    def dwg(self, geom):
        return affinity.affine_transform(geom, self.to_dwg)

    def xy(self, p) -> tuple[float, float]:
        x, y = p
        a, b, c, d, e, f = self.to_dwg
        return (a * x + b * y + e, c * x + d * y + f)

    def attribs(self, layer_key: str) -> dict:
        return {"layer": EDIT_LAYERS[layer_key][0]}

    def add_line(self, a, b, layer_key: str):
        self.layout.add_line(self.xy(a), self.xy(b), dxfattribs=self.attribs(layer_key))

    def add_lines(self, geom, layer_key: str):
        """Add (multi)line geometry given in plan coordinates."""
        g = geom if geom.geom_type != "GeometryCollection" else unary_union(
            [x for x in geom.geoms if x.geom_type in ("LineString", "MultiLineString")])
        if g.is_empty:
            return 0
        merged = linemerge(g) if g.geom_type == "MultiLineString" else g
        n = 0
        for ln in getattr(merged, "geoms", [merged]):
            if ln.geom_type == "LinearRing":
                ln = LineString(ln.coords)
            if ln.geom_type != "LineString" or ln.length < 0.02:
                continue
            pts = []
            for p in ln.coords:                      # drop repeated vertices
                q = self.xy(p)
                if not pts or math.dist(q, pts[-1]) > 1e-6:
                    pts.append(q)
            if len(pts) < 2:
                continue
            if len(pts) == 2:
                self.layout.add_line(*pts, dxfattribs=self.attribs(layer_key))
            else:
                self.layout.add_lwpolyline(pts, dxfattribs=self.attribs(layer_key))
            n += 1
        return n

    def entity_line(self, e):
        """Entity geometry as a plan-coordinate LineString (or None)."""
        try:
            pts = [(v.x, v.y) for v in make_path(e).flattening(self.flat)]
        except Exception:
            return None
        if len(pts) < 2:
            return None
        return affinity.affine_transform(LineString(pts), self.to_plan)

    # ---- operations ----------------------------------------------------
    def trim(self, region: Polygon, roles: tuple[str, ...]):
        """Cut linework of the given roles inside `region` (plan coords)."""
        n = 0
        for e in list(self.layout):
            t = e.dxftype()
            if t not in CURVES or (t == "POLYLINE" and not e.is_2d_polyline):
                continue
            if self.m.layer_role(e.dxf.layer) not in roles:
                continue
            ln = self.entity_line(e)
            if ln is None or not ln.intersects(region):
                continue
            rest = ln.difference(region)
            keep = {k: e.dxf.get(k) for k in ("layer", "color", "linetype", "lineweight", "ltscale", "true_color")
                    if e.dxf.hasattr(k)}
            self.layout.delete_entity(e)
            for piece in getattr(rest, "geoms", [rest]):
                if piece.is_empty or piece.geom_type != "LineString" or piece.length < 1e-3:
                    continue
                pts = [self.xy(p) for p in piece.coords]
                if len(pts) == 2:
                    self.layout.add_line(*pts, dxfattribs=keep)
                else:
                    self.layout.add_lwpolyline(pts, dxfattribs=keep)
            n += 1
        self.stats["trimmed"] += n

    def remove_symbols(self, region: Polygon):
        """Delete door/window symbols (incl. swing arcs, block inserts) at an opening."""
        zone = region.buffer(0.05)
        for e in list(self.layout):
            t = e.dxftype()
            role = self.m.layer_role(e.dxf.layer)
            if t == "INSERT":
                if role in ("doors", "windows") or self.m.block_role(e.dxf.name) in ("doors", "windows"):
                    p = affinity.affine_transform(Point(e.dxf.insert.x, e.dxf.insert.y), self.to_plan)
                    if zone.buffer(0.5).contains(p):
                        self.layout.delete_entity(e)
                        self.stats["symbols_removed"] += 1
                continue
            if t not in CURVES:
                continue
            is_swing = (t == "ARC" and 75 <= (e.dxf.end_angle - e.dxf.start_angle) % 360 <= 105
                        and role not in ("walls", "columns", "grid"))
            if role not in ("doors", "windows") and not is_swing:
                continue
            ln = self.entity_line(e)
            if ln is None:
                continue
            hit = ln.intersects(zone) if not is_swing else \
                zone.distance(affinity.affine_transform(Point(e.dxf.center.x, e.dxf.center.y), self.to_plan)) < 0.2
            if hit:
                self.layout.delete_entity(e)
                self.stats["symbols_removed"] += 1

    def jambs(self, walls_after, region: Polygon):
        """Wall end lines along the cut boundary: only where wall material
        continues right outside the cut (not slivers along a wall face)."""
        edge = walls_after.boundary.intersection(region.exterior.buffer(0.004))
        g = edge if edge.geom_type != "GeometryCollection" else unary_union(
            [x for x in edge.geoms if x.geom_type in ("LineString", "MultiLineString")])
        if g.is_empty:
            return
        g = linemerge(g) if g.geom_type == "MultiLineString" else g
        inner = region.buffer(-1e-4)
        keep = []
        for ln in getattr(g, "geoms", [g]):
            if ln.geom_type != "LineString" or ln.length < 0.02:
                continue
            (x0, y0), (x1, y1) = ln.coords[0], ln.coords[-1]
            L = math.hypot(x1 - x0, y1 - y0) or 1
            m = ln.interpolate(0.5, normalized=True)
            nx, ny = -(y1 - y0) / L * 0.012, (x1 - x0) / L * 0.012
            for sx in (1, -1):
                q = Point(m.x + nx * sx, m.y + ny * sx)
                if not inner.contains(q) and walls_after.contains(q):
                    keep.append(ln)
                    break
        if keep:
            self.stats["lines_added"] += self.add_lines(unary_union(keep), "walls")

    def symbol(self, o: Opening, kind: str):
        u = np.array(o.direction, float)
        n = np.array((-u[1], u[0]))
        c = np.array(o.center, float)
        hw, hd = o.width / 2, max(o.depth, 0.05) / 2
        if kind in ("window", "vitrage"):
            for k in (-1, 0, 1):
                self.add_line(c - u * hw + n * hd * k, c + u * hw + n * hd * k,
                              "vitrage" if kind == "vitrage" else "windows")
            self.stats["windows"] += 1
        elif kind == "door":
            hinge = c - u * hw + n * hd
            tip = hinge + n * o.width
            self.add_line(hinge, tip, "doors")
            a_leaf = math.degrees(math.atan2(n[1], n[0]))
            a_wall = math.degrees(math.atan2(u[1], u[0]))
            # ezdxf arcs run counter-clockwise: pick the order giving the 90° sweep
            start, end = (a_wall, a_leaf) if abs((a_leaf - a_wall) % 360 - 90) < 1 else (a_leaf, a_wall)
            self.layout.add_arc(self.xy(hinge), o.width / self.s, start, end, dxfattribs=self.attribs("doors"))
            self.stats["doors"] += 1
        elif kind == "wall":
            for k in (-1, 1):
                self.add_line(c - u * hw + n * hd * k, c + u * hw + n * hd * k, "walls")
            self.stats["filled"] += 1

    def rename_room(self, room_poly: Polygon, at, name: str):
        best = None
        for e in self.layout.query("TEXT MTEXT"):
            ins = e.dxf.insert
            p = affinity.affine_transform(Point(ins.x, ins.y), self.to_plan)
            if not room_poly.contains(p):
                continue
            txt = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
            if parse_mark(txt) is not None or _RE_NUMERIC.match(txt.strip()):
                continue
            h = e.dxf.get("char_height" if e.dxftype() == "MTEXT" else "height", 0) or 0
            if best is None or h > best[0]:
                best = (h, e)
        if best:
            e = best[1]
            if e.dxftype() == "MTEXT":
                e.text = name
            else:
                e.dxf.text = name
        else:
            t = self.layout.add_text(name, height=0.3 / self.s, dxfattribs=self.attribs("text"))
            t.set_placement(self.xy(at), align=TextEntityAlignment.MIDDLE_CENTER)
        self.stats["rooms"] += 1


def _apply_floor(w: _FloorWriter, plan: FloorPlan, edits: dict):
    dbg = plan.debug
    wall_roles = ("walls", "insulation")
    erase = dbg.get("erase")
    if erase is not None and not erase.is_empty:
        for region in _polys(erase):
            w.trim(region, wall_roles)
            w.jambs(plan.walls, region)
    for poly in dbg.get("added_walls") or []:
        w.stats["lines_added"] += w.add_lines(poly.exterior, "walls")
    for o in plan.openings:
        if o.source != "manual":
            continue
        w.trim(o.poly, wall_roles)
        w.remove_symbols(o.poly)
        w.jambs(plan.walls, o.poly)
        w.symbol(o, o.kind)
    for o, kind in dbg.get("kind_changes") or []:
        w.remove_symbols(o.poly)
        if o.source == "block" and kind not in ("wall", "none"):
            # the opening existed only as a block on a continuous wall:
            # now that the block is gone, cut the wall for the new symbol
            w.trim(o.poly, wall_roles)
            w.jambs(plan.walls, o.poly)
        if kind != "none":
            w.symbol(o, kind)
    for e in edits.get("rooms") or []:
        pt = Point(e["at"])
        room = next((r for r in plan.rooms if r.poly.contains(pt)), None)
        if room is not None:
            w.rename_room(room.poly, e["at"], str(e.get("name", "")))


def repair_for_save(doc):
    """DXF files produced by DWG converters (LibreDWG especially) often carry
    dangling references that ezdxf refuses to write back. Fix the common ones."""
    from ezdxf.render.arrows import ARROWS

    mats = doc.materials
    for name in ("ByLayer", "ByBlock", "Global"):
        if not hasattr(mats.get(name), "dxf"):
            mats.object_dict.discard(name)
    mats.create_required_entries()
    doc.audit()
    for ds in doc.dimstyles:
        st = ds.dxf.get("dimtxsty")
        if st and st not in doc.styles:
            doc.styles.new(st, dxfattribs={"font": "arial.ttf"})
        for k in ("dimblk", "dimblk1", "dimblk2", "dimldrblk"):
            v = ds.dxf.get(k)
            if v and not ARROWS.is_acad_arrow(v) and v not in doc.blocks:
                ds.dxf.set(k, "")


def export_edited_dxf(src: Path, out: Path, config: dict | None = None) -> dict:
    """Apply `config['edits']` to the DXF `src` and save to `out`."""
    cfg = load_config(config)
    doc = read_doc(src)
    d = read_drawing(src, cfg, doc=doc)
    cands = detect_candidates(d, cfg)
    apply_manual(cands, cfg)
    floors = resolve_stack(cands, cfg)
    align_floors(d, floors, cfg)
    mapper = LayerMapper(cfg)
    for key, (name, color) in EDIT_LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    stats = {k: 0 for k in ("floors", "trimmed", "lines_added", "symbols_removed",
                            "windows", "doors", "filled", "rooms")}
    all_edits = cfg.get("edits") or {}
    for f in floors:
        e = all_edits.get(f.id) or {}
        if not any(e.values()):
            continue
        shapes = [s for s in d.shapes if f.contains(s, margin=1.0)]
        texts = [t for t in d.texts if f.contains(t)]
        inserts = [x for x in d.inserts if f.contains(x, margin=1.0)]
        plan = build_plan(shapes, texts, inserts, cfg, offset=f.offset, edits=e)
        layout = doc.modelspace() if f.space == "Model" else doc.layouts.get(f.space)
        _apply_floor(_FloorWriter(doc, layout, f, d.scale, mapper, stats), plan, e)
        stats["floors"] += 1
    repair_for_save(doc)
    tmp = Path(out).with_suffix(".tmp")
    doc.saveas(str(tmp))              # write-then-rename: no half-written file on failure
    tmp.replace(out)
    return stats


def dxf_to_dwg(src: Path, dst: Path, timeout: int = 600, libredwg_timeout: int = 60) -> str:
    """DXF -> DWG via ODA File Converter, else LibreDWG dxf2dwg (experimental)."""
    import os
    import shutil
    import subprocess
    import tempfile

    errors = []
    if oda := find_oda():
        with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
            shutil.copy(src, Path(tin) / "out.dxf")
            r = subprocess.run([oda, tin, tout, "ACAD2018", "DWG", "0", "1", "*.DXF"],
                               capture_output=True, text=True, timeout=timeout,
                               env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
            res = Path(tout) / "out.dwg"
            if res.exists() and res.stat().st_size:
                shutil.move(res, dst)
                return "oda"
            errors.append(f"ODA: {(r.stderr or r.stdout).strip()[-300:]}")
    lr = find_libredwg()
    tool = Path(lr).with_name("dxf2dwg") if lr else None
    if tool and tool.exists():
        try:
            # experimental writer: it may crash or loop forever on complex drawings
            r = subprocess.run([str(tool), "-y", "-o", str(dst), str(src)], capture_output=True, text=True,
                               timeout=libredwg_timeout)
            if dst.exists() and dst.stat().st_size and r.returncode == 0:
                return "libredwg"
            errors.append(f"LibreDWG dxf2dwg: код {r.returncode}")
        except subprocess.TimeoutExpired:
            errors.append("LibreDWG dxf2dwg: превышено время")
        if dst.exists():
            dst.unlink()
    if not errors:
        raise ConversionError("Нет конвертера DXF→DWG (ODA File Converter или LibreDWG)")
    raise ConversionError(
        "Не удалось записать DWG (" + "; ".join(errors) + "). Скачайте DXF — он открывается в AutoCAD; "
        "для надёжной записи DWG установите ODA File Converter.")
