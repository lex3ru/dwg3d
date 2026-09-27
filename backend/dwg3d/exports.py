"""Model exports besides glTF: IFC4 (BIM) and OBJ (+MTL, zipped)."""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import LineString

from .geometry import FloorPlan, _polys
from .model3d import COLORS, _pane

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ IFC ---
class _Ifc:
    def __init__(self, name: str, center):
        import ifcopenshell
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.context
        import ifcopenshell.api.geometry
        import ifcopenshell.api.root
        import ifcopenshell.api.spatial
        import ifcopenshell.api.unit
        import ifcopenshell.api.pset

        self.api = ifcopenshell.api
        self.f = f = ifcopenshell.file(schema="IFC4")
        self.cx, self.cy = center
        self.project = self.api.root.create_entity(f, "IfcProject", name=name)
        self.api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"},
                                  area={"is_metric": True, "raw": "SQUARE_METERS"},
                                  volume={"is_metric": True, "raw": "CUBIC_METERS"})
        model = self.api.context.add_context(f, context_type="Model")
        self.body = self.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                 target_view="MODEL_VIEW", parent=model)
        self.site = self.api.root.create_entity(f, "IfcSite", name="Участок")
        self.building = self.api.root.create_entity(f, "IfcBuilding", name=name)
        self.api.aggregate.assign_object(f, products=[self.site], relating_object=self.project)
        self.api.aggregate.assign_object(f, products=[self.building], relating_object=self.site)
        for p in (self.site, self.building):
            self._place(p, 0.0)
        self._origin = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
        self._up = f.createIfcDirection((0.0, 0.0, 1.0))

    def _place(self, product, z):
        m = np.eye(4)
        m[2, 3] = z
        self.api.geometry.edit_object_placement(self.f, product=product, matrix=m)

    def _curve(self, ring):
        pts = [self.f.createIfcCartesianPoint((float(x - self.cx), float(y - self.cy))) for x, y in ring.coords]
        return self.f.createIfcPolyline(pts)

    def solids(self, geom, z0, z1):
        """Extruded solids (absolute z) for every polygon of geom."""
        out = []
        if z1 - z0 <= 1e-4:
            return out
        for p in _polys(geom):
            if p.area < 1e-5:
                continue
            p = p.simplify(0.001)
            if p.is_empty or p.geom_type != "Polygon":
                continue
            if p.interiors:
                prof = self.f.createIfcArbitraryProfileDefWithVoids(
                    "AREA", None, self._curve(p.exterior), [self._curve(r) for r in p.interiors])
            else:
                prof = self.f.createIfcArbitraryClosedProfileDef("AREA", None, self._curve(p.exterior))
            pos = self.f.createIfcAxis2Placement3D(self.f.createIfcCartesianPoint((0.0, 0.0, float(z0))))
            out.append(self.f.createIfcExtrudedAreaSolid(prof, pos, self._up, float(z1 - z0)))
        return out

    def element(self, ifc_class, name, solids, storey, predefined=None, psets=None, container=True):
        if not solids:
            return None
        el = self.api.root.create_entity(self.f, ifc_class, name=name, predefined_type=predefined)
        self._place(el, 0.0)
        rep = self.f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", solids)
        self.api.geometry.assign_representation(self.f, product=el, representation=rep)
        if container:
            self.api.spatial.assign_container(self.f, products=[el], relating_structure=storey)
        for pname, props in (psets or {}).items():
            ps = self.api.pset.add_pset(self.f, product=el, name=pname)
            self.api.pset.edit_pset(self.f, pset=ps, properties=props)
        return el

    def storey(self, name, elevation):
        s = self.api.root.create_entity(self.f, "IfcBuildingStorey", name=name)
        s.Elevation = float(elevation)
        self.api.aggregate.assign_object(self.f, products=[s], relating_object=self.building)
        self._place(s, elevation)
        return s


def export_ifc(path: Path, floors, plans: list[FloorPlan], cfg: dict, center, name="Здание"):
    b = cfg["building"]
    slab_t = float(b["slab_thickness"])
    ifc = _Ifc(name, center)
    for f, plan in zip(floors, plans):
        st = ifc.storey(f.name, f.elevation)
        e = f.elevation
        top = e + f.height - slab_t
        door_h = min(float(b["door_height"]), top - e - 0.05)
        sill = float(b["window_sill"])
        head = min(float(b["window_head"]), top - e - 0.05)
        v_head = max(head, top - e - float(b.get("vitrage_head", 0.15)))
        for i, p in enumerate(_polys(plan.wall_parts.get("wall", plan.walls))):
            ifc.element("IfcWall", f"Стена {i + 1}", ifc.solids(p, e, top), st, "SOLIDWALL")
        for i, p in enumerate(_polys(plan.wall_parts.get("partition"))):
            ifc.element("IfcWall", f"Перегородка {i + 1}", ifc.solids(p, e, top), st, "PARTITIONING")
        for i, p in enumerate(_polys(plan.columns)):
            ifc.element("IfcColumn", f"Колонна {i + 1}", ifc.solids(p, e, top), st, "COLUMN")
        ifc.element("IfcSlab", "Перекрытие", ifc.solids(plan.footprint, e - slab_t, e), st, "FLOOR")
        lintels = []
        for o in plan.openings:
            if o.kind == "door":
                lintels += ifc.solids(o.poly, e + door_h, top)
                leaves = [LineString([h, t]).buffer(0.02, cap_style="flat") for h, t in o.leaves] or [_pane(o, 0.04)]
                ifc.element("IfcDoor", "Дверь", [s for lf in leaves for s in ifc.solids(lf, e, e + door_h)], st,
                            "DOOR", {"Pset_DoorCommon": {"Reference": o.id}})
            elif o.kind in ("window", "vitrage"):
                lo, hi = (sill, head) if o.kind == "window" else (0.0, v_head)
                if lo > 0:
                    lintels += ifc.solids(o.poly, e, e + lo)
                lintels += ifc.solids(o.poly, e + hi, top)
                ifc.element("IfcWindow", "Витраж" if o.kind == "vitrage" else "Окно",
                            ifc.solids(_pane(o, 0.05), e + lo, e + hi), st, "WINDOW")
        ifc.element("IfcWall", "Перемычки и подоконные части", lintels, st, "SOLIDWALL")
        for i, stair in enumerate(plan.stairs):
            riser = float(b.get("riser", 0.165))
            sol = [s for k, t in enumerate(stair.treads) for s in ifc.solids(t, e, min(e + (k + 1) * riser, top))]
            ifc.element("IfcStair", f"Лестница {i + 1}", sol, st, "STRAIGHT_RUN_STAIR")
        for i, r in enumerate(plan.rooms):
            sp = ifc.element("IfcSpace", str(i + 1), ifc.solids(r.poly, e, top), st, "INTERNAL",
                             {"Qto_SpaceBaseQuantities": {"NetFloorArea": float(r.area)}}, container=False)
            if sp is not None:
                sp.LongName = r.name or None
                ifc.api.aggregate.assign_object(ifc.f, products=[sp], relating_object=st)
    if cfg["building"].get("roof", True) and floors:
        f, plan = floors[-1], plans[-1]
        st = ifc.storey("Кровля", f.elevation + f.height)
        z = f.elevation + f.height
        ifc.element("IfcSlab", "Кровля", ifc.solids(plan.footprint, z - slab_t, z), st, "ROOF")
    ifc.f.write(str(path))


# ------------------------------------------------------------------ OBJ ---
def export_obj_zip(path: Path, meshes: dict[str, trimesh.Trimesh]):
    """All meshes (Y-up, like glTF) into model.obj + model.mtl, zipped."""
    scene = trimesh.Scene()
    rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])   # Z-up -> Y-up
    for name, m in meshes.items():
        role = next((k for k in COLORS if name.endswith("_" + k) or name == k), None)
        if role is None:
            role = "room" if "_room_" in name else "walls"
        mm = m.copy()
        mm.apply_transform(rot)
        rgba = (np.array(COLORS[role]) * 255).astype(np.uint8)
        mm.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.SimpleMaterial(name=role, diffuse=rgba))
        scene.add_geometry(mm, node_name=name, geom_name=name)
    text, tex = trimesh.exchange.obj.export_obj(scene, include_texture=True, return_texture=True,
                                                mtl_name="model.mtl")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("model.obj", text)
        for fname, data in tex.items():
            z.writestr(fname, data)
