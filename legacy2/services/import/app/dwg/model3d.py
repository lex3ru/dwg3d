"""2D plans -> 3D meshes -> GLB scene.

Openings are produced in 2.5D: the wall mass without the opening footprint
is extruded full height, and the opening footprint itself is extruded only
below the sill and above the head (lintel). This is exactly what a 3D
boolean subtract of an opening box from the wall would produce, without the
fragility of mesh booleans.

Axes: plan X -> glTF X, plan Y -> glTF -Z, elevation -> glTF Y (Y-up).
"""
from __future__ import annotations

import logging
import math

import numpy as np
import trimesh
from shapely.geometry import LineString, Polygon

from .geometry import FloorPlan, _polys
from .gltf import GLBWriter
from .semantics import label_frame

log = logging.getLogger(__name__)

COLORS = {
    "walls": (0.93, 0.91, 0.87, 1.0),
    "partitions": (0.86, 0.89, 0.93, 1.0),
    "columns": (0.80, 0.77, 0.72, 1.0),
    "slab": (0.72, 0.70, 0.66, 1.0),
    "roof": (0.55, 0.57, 0.60, 1.0),
    "glass": (0.55, 0.75, 0.95, 0.35),
    "doors": (0.66, 0.50, 0.36, 1.0),
    "stairs": (0.78, 0.74, 0.68, 1.0),
    "room": (0.97, 0.95, 0.90, 1.0),
    "edges": (0.30, 0.32, 0.35, 1.0),
}
EDGE_ROLES = {"walls", "partitions", "columns", "slab", "roof", "stairs", "doors"}


def extrude(geom, z0: float, z1: float) -> list[trimesh.Trimesh]:
    out = []
    if z1 - z0 <= 1e-4:
        return out
    for p in _polys(geom):
        if p.area < 1e-5:
            continue
        for q in _polys(p.buffer(0)):
            try:
                m = trimesh.creation.extrude_polygon(q, z1 - z0)
            except Exception as ex:  # degenerate polygons
                log.debug("extrude failed: %s", ex)
                continue
            m.apply_translation((0, 0, z0))
            out.append(m)
    return out


def _pane(o, t=0.03) -> Polygon:
    c = np.array(o.center)
    u = np.array(o.direction)
    line = LineString([c - u * (o.width / 2 + 0.2), c + u * (o.width / 2 + 0.2)])
    return line.buffer(t / 2, cap_style="flat").intersection(o.poly)


def feature_edges(m: trimesh.Trimesh, angle_deg=25.0) -> np.ndarray:
    """Vertex index pairs of sharp and boundary edges."""
    sharp = m.face_adjacency_edges[m.face_adjacency_angles > math.radians(angle_deg)]
    boundary = m.edges_sorted[trimesh.grouping.group_rows(m.edges_sorted, require_count=1)]
    return np.vstack([sharp, boundary]) if len(boundary) else sharp


class SceneBuilder:
    def __init__(self, cfg: dict, center=(0.0, 0.0)):
        self.cfg = cfg
        self.w = GLBWriter()
        self.cx, self.cy = center
        self.mat = {k: self.w.material(k, v, blend=v[3] < 1, double_sided=k in ("glass", "doors"),
                                       roughness=0.2 if k == "glass" else 0.85, unlit=k == "edges")
                    for k, v in COLORS.items()}
        self.tri_count = 0
        self.meshes: dict[str, trimesh.Trimesh] = {}   # kept for OBJ/IFC export

    def _to_gltf(self, v):
        return np.column_stack([v[:, 0], v[:, 2], -v[:, 1]])

    def _add(self, name, meshes, role, extras=None) -> int | None:
        meshes = [m for m in meshes if len(m.faces)]
        if not meshes:
            return None
        m = trimesh.util.concatenate(meshes)
        m.apply_translation((-self.cx, -self.cy, 0))
        m.merge_vertices()
        self.meshes[name] = m
        children = []
        if role in EDGE_ROLES:
            e = feature_edges(m)
            if len(e):
                ei = self.w.mesh(f"{name}_edges", self._to_gltf(np.asarray(m.vertices)), None, e,
                                 self.mat["edges"], mode=1)
                children.append(self.w.node(f"{name}_edges", mesh=ei, extras={"role": "edges"}))
        # sharp edges on flat walls, smooth shading on curved ones
        try:
            m = trimesh.graph.smooth_shade(m, angle=math.radians(25))
        except Exception:
            pass
        v = np.asarray(m.vertices)
        nrm = np.asarray(m.vertex_normals)
        self.tri_count += len(m.faces)
        mi = self.w.mesh(name, self._to_gltf(v), self._to_gltf(nrm), np.asarray(m.faces), self.mat[role])
        node = self.w.node(name, mesh=mi, extras={**(extras or {}), "role": role})
        if children:
            self.w.nodes[node]["children"] = children
        return node

    def floor(self, fid: str, plan: FloorPlan, elevation: float, height: float, extras: dict,
              room_types: list[str] | None = None) -> tuple[int, list]:
        b = self.cfg["building"]
        slab_t = float(b["slab_thickness"])
        e = elevation
        top = e + height - slab_t
        if top - e < 1.0:        # pathological heights
            top = e + max(height, 2.0)
        children, rooms_meta = [], []
        prefix = f"floor_{fid}"

        walls = extrude(plan.wall_parts.get("wall", plan.walls), e, top)
        partitions = extrude(plan.wall_parts.get("partition"), e, top) if plan.wall_parts else []
        door_h = min(float(b["door_height"]), top - e - 0.05)
        sill = float(b["window_sill"])
        head = min(float(b["window_head"]), top - e - 0.05)
        v_head = max(head, top - e - float(b.get("vitrage_head", 0.15)))
        glass, doors = [], []
        for o in plan.openings:
            if o.kind == "door":
                walls += extrude(o.poly, e + door_h, top)
                for hinge, tip in o.leaves:
                    leaf = LineString([hinge, tip]).buffer(0.02, cap_style="flat")
                    doors += extrude(leaf, e + 0.01, e + door_h - 0.01)
            elif o.kind == "window":
                if sill > 0:
                    walls += extrude(o.poly, e, e + sill)
                walls += extrude(o.poly, e + head, top)
                glass += extrude(_pane(o), e + sill, e + head)
            elif o.kind == "vitrage":
                walls += extrude(o.poly, e + v_head, top)
                glass += extrude(_pane(o), e, e + v_head)
        stairs = []
        riser = float(b.get("riser", 0.165))
        for st in plan.stairs:
            for i, tread in enumerate(st.treads):
                stairs += extrude(tread, e, min(e + (i + 1) * riser, top))
        for nm, meshes, role in ((f"{prefix}_walls", walls, "walls"),
                                 (f"{prefix}_partitions", partitions, "partitions"),
                                 (f"{prefix}_columns", extrude(plan.columns, e, top), "columns"),
                                 (f"{prefix}_slab", extrude(plan.footprint, e - slab_t, e), "slab"),
                                 (f"{prefix}_stairs", stairs, "stairs"),
                                 (f"{prefix}_doors", doors, "doors"),
                                 (f"{prefix}_glass", glass, "glass")):
            n = self._add(nm, meshes, role)
            if n is not None:
                children.append(n)
        for i, r in enumerate(plan.rooms):
            nm = f"{prefix}_room_{i}"
            rtype = room_types[i] if room_types else "other"
            n = self._add(nm, extrude(r.poly.buffer(-0.01), e + 0.003, e + 0.02), "room",
                          {"name": r.name, "area": r.area, "type": rtype})
            if n is not None:
                children.append(n)
                lf = label_frame(r.poly)
                rooms_meta.append({"node": nm, "name": r.name, "area": r.area, "type": rtype,
                                   "label_pos": [round(lf["x"] - self.cx, 3), round(e + 0.05, 3),
                                                 round(-(lf["y"] - self.cy), 3)],
                                   # text on the floor: glTF rotation about Y, wrap width, room depth
                                   "label_angle": lf["angle"], "label_w": lf["w"], "label_d": lf["d"]})
        node = self.w.node(prefix, children=children, extras=extras)
        return node, rooms_meta

    def roof(self, footprint, z: float) -> int | None:
        slab_t = float(self.cfg["building"]["slab_thickness"])
        return self._add("roof", extrude(footprint, z - slab_t, z), "roof")

    def save(self, path, roots, extras=None):
        self.w.save(path, roots, extras)
