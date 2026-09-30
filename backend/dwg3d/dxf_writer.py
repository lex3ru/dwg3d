"""Write the 2D-editor corrections — and the objects of the project's
layers — back into the source drawing (DXF/DWG).

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
from .convert import ConversionError, find_libredwg, find_oda, limits
from .edits import has_edits as edits_nonempty
from .edits import resolve_edits, resolve_items
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
    return any(edits_nonempty(e) for e in (cfg.get("edits") or {}).values())


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


def export_edited_dxf(src: Path, out: Path, config: dict | None = None, project_layers: dict | None = None) -> dict:
    """Apply `config['edits']` to the DXF `src`, draw the objects of
    `project_layers` (see add_project_layers) and save to `out`."""
    cfg = load_config(config)
    doc = read_doc(src)
    d = read_drawing(src, cfg, doc=doc)
    cands = detect_candidates(d, cfg)
    resolve_items(cfg, cands)
    apply_manual(cands, cfg)
    floors = resolve_stack(cands, cfg)
    align_floors(d, floors, cfg)
    # the same re-anchoring as the 3D build: edits land on the sheet they were made on
    applied, _, _, _ = resolve_edits(cfg, floors)
    mapper = LayerMapper(cfg)
    for key, (name, color) in EDIT_LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    stats = {k: 0 for k in ("floors", "trimmed", "lines_added", "symbols_removed",
                            "windows", "doors", "filled", "rooms")}
    for f in floors:
        e = applied.get(f.id) or {}
        if not edits_nonempty(e):
            continue
        shapes = [s for s in d.shapes if f.contains(s, margin=1.0)]
        texts = [t for t in d.texts if f.contains(t)]
        inserts = [x for x in d.inserts if f.contains(x, margin=1.0)]
        plan = build_plan(shapes, texts, inserts, cfg, offset=f.offset, edits=e)
        layout = doc.modelspace() if f.space == "Model" else doc.layouts.get(f.space)
        _apply_floor(_FloorWriter(doc, layout, f, d.scale, mapper, stats), plan, e)
        stats["floors"] += 1
    if project_layers:
        stats["layers"] = add_project_layers(doc, {f.id: f for f in floors}, d.scale, project_layers)
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
                               env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                               preexec_fn=limits(timeout, memory=False))
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
                               timeout=libredwg_timeout, preexec_fn=limits(libredwg_timeout, memory=True))
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


# ------------------------------------------------------ project layers ---
# Objects of the project's layers go to one DXF layer each ("3D_<layer name>"):
# catalog items as blocks (footprint + front edge, attributes NAME / ARTICLE /
# NOTE for data extraction), CCTV cameras also with their field of view,
# routes as polylines with numbered stops, zones as outlines with a hatch.
LAYER_COLORS = {"furniture": 150, "cctv": 6, "routes": 5, "zones": 3}
_BAD_NAME = re.compile(r'[<>/\\":;?*|=`]')


def dxf_layer_name(name: str) -> str:
    return ("3D_" + _BAD_NAME.sub("_", name).strip())[:250]


def _rgb(hexcolor: str | None) -> int | None:
    if not hexcolor or not re.fullmatch(r"#[0-9a-fA-F]{6}", hexcolor):
        return None
    from ezdxf.colors import rgb2int
    return rgb2int((int(hexcolor[1:3], 16), int(hexcolor[3:5], 16), int(hexcolor[5:7], 16)))


def _item_block(doc, item: dict, scale: float) -> str:
    """A block of a catalog item: its footprint (w x d, in drawing units of
    this file) centred on the origin, the front edge marked, attributes."""
    name = "3D_" + re.sub(r"[^0-9A-Za-z_.-]", "_", item["id"])
    if name in doc.blocks:
        return name
    blk = doc.blocks.new(name)
    w, d = item["w"] / scale, item["d"] / scale
    blk.add_lwpolyline([(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)], close=True,
                       dxfattribs={"layer": "0"})
    blk.add_line((-w / 2, -d / 2 + d * 0.08), (w / 2, -d / 2 + d * 0.08), dxfattribs={"layer": "0"})
    h = max(min(w, d) * 0.12, 0.05 / scale)
    for tag, y in (("NAME", 0.0), ("ARTICLE", -h * 1.5), ("NOTE", -h * 3)):
        a = blk.add_attdef(tag, insert=(0, y), height=h, dxfattribs={"layer": "0"})
        a.set_placement((0, y), align=TextEntityAlignment.MIDDLE_CENTER)
        a.is_invisible = tag != "NAME"
    return name


def add_project_layers(doc, floors: dict, scale: float, payload: dict) -> dict:
    """Draw the objects of project layers into the floors' layouts.
    floors: floor id (candidate of the current build) -> the Floor of this file.
    payload: {"layers": [{id, name, kind}], "objects": [object JSON],
              "catalog": {item id: {id, name, w, d, h, article, cam?}}, "flows": {...}, "zone_kinds": {...}}"""
    stats = {"objects": 0, "blocks": 0, "routes": 0, "zones": 0, "skipped": 0}
    layer_of = {}
    for lay in payload.get("layers") or []:
        nm = dxf_layer_name(lay["name"])
        if nm not in doc.layers:
            doc.layers.add(nm, color=LAYER_COLORS.get(lay.get("kind"), 7))
        layer_of[lay["id"]] = nm
    catalog = payload.get("catalog") or {}
    flows, zone_kinds = payload.get("flows") or {}, payload.get("zone_kinds") or {}
    cables = payload.get("cables") or {}

    def writer(fid: str):
        f = floors.get(fid)
        if f is None:
            return None
        layout = doc.modelspace() if f.space == "Model" else doc.layouts.get(f.space)
        return _FloorWriter(doc, layout, f, scale, None, {})

    for o in payload.get("objects") or []:
        dxl = layer_of.get(o.get("layer"))
        geom = o.get("geom") or "point"
        if dxl is None:
            continue
        if geom == "route":
            props = o.get("props") or {}
            color = _rgb((flows.get(props.get("flow")) or {}).get("color"))
            attrs = {"layer": dxl, **({"true_color": color} if color else {})}
            drawn = False
            for sg in props.get("path") or []:
                w = writer(sg.get("floor"))
                if w is None or len(sg.get("pts") or []) < 2:
                    continue
                w.layout.add_lwpolyline([w.xy(p) for p in sg["pts"]], dxfattribs=attrs)
                drawn = True
            for k, st in enumerate(props.get("stops") or []):
                w = writer(st.get("floor"))
                if w is None:
                    continue
                c = w.xy(st["at"])
                w.layout.add_circle(c, 0.25 / scale, dxfattribs=attrs)
                t = w.layout.add_text(f"{k + 1}. {st.get('label') or ''}".strip(), height=0.3 / scale, dxfattribs=attrs)
                t.set_placement((c[0] + 0.35 / scale, c[1]), align=TextEntityAlignment.MIDDLE_LEFT)
                drawn = True
            stats["routes" if drawn else "skipped"] += 1
            continue
        w = writer(o.get("floor"))
        if w is None:
            stats["skipped"] += 1
            continue
        if geom in ("polygon", "polyline"):
            pts = [w.xy(p) for p in o.get("points") or []]
            if len(pts) < 2:
                continue
            props = o.get("props") or {}
            spec = zone_kinds.get(props.get("zone")) if geom == "polygon" else cables.get(props.get("cable"))
            color = _rgb((spec or {}).get("color"))
            attrs = {"layer": dxl, **({"true_color": color} if color else {})}
            w.layout.add_lwpolyline(pts, close=geom == "polygon", dxfattribs=attrs)
            if geom == "polygon" and len(pts) >= 3:
                hatch = w.layout.add_hatch(dxfattribs=attrs)
                hatch.set_pattern_fill("ANSI31", scale=0.5 / scale)
                hatch.paths.add_polyline_path(pts, is_closed=True)
                if props.get("name"):
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                    t = w.layout.add_text(props["name"], height=0.3 / scale, dxfattribs=attrs)
                    t.set_placement((cx, cy), align=TextEntityAlignment.MIDDLE_CENTER)
            stats["zones" if geom == "polygon" else "lines"] = stats.get("zones" if geom == "polygon" else "lines", 0) + 1
            continue
        item = catalog.get(o.get("item"))
        if item is None:
            stats["skipped"] += 1
            continue
        bname = _item_block(doc, item, scale)
        size = o.get("size") or [item["w"], item["d"], item["h"]]
        ref = w.layout.add_blockref(bname, w.xy(o["at"]), dxfattribs={
            "layer": dxl, "rotation": float(o.get("angle") or 0),
            "xscale": size[0] / item["w"] if item["w"] else 1, "yscale": size[1] / item["d"] if item["d"] else 1})
        ref.add_auto_attribs({"NAME": item.get("name") or item["id"], "ARTICLE": item.get("article") or "",
                              "NOTE": o.get("note") or ""})
        stats["blocks"] += 1
        cam = item.get("cam")
        if cam:
            fov = float(o.get("fov") or cam.get("fov") or 90)
            rng = float(o.get("range") or cam.get("range") or 10)
            a0 = float(o.get("angle") or 0) + 90       # the front of an item faces -Y in its own frame: rotate
            c = w.xy(o["at"])
            r = rng / scale
            if fov >= 359:
                w.layout.add_circle(c, r, dxfattribs={"layer": dxl})
            else:
                s0, s1 = a0 - 180 - fov / 2, a0 - 180 + fov / 2
                w.layout.add_arc(c, r, s0, s1, dxfattribs={"layer": dxl})
                for ang in (s0, s1):
                    w.layout.add_line(c, (c[0] + r * math.cos(math.radians(ang)), c[1] + r * math.sin(math.radians(ang))),
                                      dxfattribs={"layer": dxl})
        stats["objects"] += 1
    return stats
