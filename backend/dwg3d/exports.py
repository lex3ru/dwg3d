"""Model exports besides glTF: IFC4 (BIM) and OBJ (+MTL, zipped)."""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import LineString
from shapely.ops import unary_union

from .geometry import FloorPlan, _opening_rect, _polys
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
        self._contained: dict = {}
        self._spaces: dict = {}
        import ifcopenshell.guid
        self.guid = ifcopenshell.guid.new

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

    # Elements are created with plain entity constructors and their spatial
    # relations are written once per storey in finish(): the high-level
    # ifcopenshell.api calls recompute placements per element and made the
    # export of a 13-storey building take >10 s.
    def element(self, ifc_class, name, solids, storey, predefined=None, psets=None, container=True,
                rel_to=None):
        if not solids:
            return None
        f = self.f
        el = f.create_entity(ifc_class, GlobalId=self.guid(), Name=name)
        if predefined:
            el.PredefinedType = predefined
        # solids carry absolute z: cancel the storey elevation in the placement
        parent = (rel_to or storey).ObjectPlacement
        z = 0.0 if rel_to is not None else -float(storey.Elevation or 0.0)
        el.ObjectPlacement = f.createIfcLocalPlacement(
            parent, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, z))))
        rep = f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", solids)
        el.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
        if container:
            self._contained.setdefault(storey, []).append(el)
        for pname, props in (psets or {}).items():
            ps = self.api.pset.add_pset(f, product=el, name=pname)
            self.api.pset.edit_pset(f, pset=ps, properties=props)
        return el

    def void(self, opening, wall):
        self.f.createIfcRelVoidsElement(self.guid(), None, None, None, wall, opening)

    def fill(self, opening, element):
        self.f.createIfcRelFillsElement(self.guid(), None, None, None, opening, element)

    def space(self, space, storey):
        self._spaces.setdefault(storey, []).append(space)

    def storey(self, name, elevation):
        s = self.api.root.create_entity(self.f, "IfcBuildingStorey", name=name)
        s.Elevation = float(elevation)
        self.api.aggregate.assign_object(self.f, products=[s], relating_object=self.building)
        self._place(s, elevation)
        return s

    def finish(self):
        for st, els in self._contained.items():
            self.f.createIfcRelContainedInSpatialStructure(self.guid(), None, None, None, els, st)
        for st, sps in self._spaces.items():
            self.f.createIfcRelAggregates(self.guid(), None, None, None, st, sps)


def _ifc_opening(ifc, o, wall, storey, e, door_h, sill, head, v_head):
    lo, hi = {"door": (0.0, door_h), "window": (sill, head), "vitrage": (0.0, v_head)}[o.kind]
    void = None
    if wall is not None:
        void = ifc.element("IfcOpeningElement", o.id, ifc.solids(_opening_rect(o, 0.1), e + lo, e + hi), storey,
                           "OPENING", container=False, rel_to=wall)
        if void is not None:
            ifc.void(void, wall)
    if o.kind == "door":
        leaves = [LineString([h, t]).buffer(0.02, cap_style="flat") for h, t in o.leaves] or [_pane(o, 0.04)]
        fill = ifc.element("IfcDoor", "Дверь", [s for lf in leaves for s in ifc.solids(lf, e + lo, e + hi)],
                           storey, "DOOR", {"Pset_DoorCommon": {"Reference": o.id}})
    else:
        fill = ifc.element("IfcWindow", "Витраж" if o.kind == "vitrage" else "Окно",
                           ifc.solids(_pane(o, 0.05), e + lo, e + hi), storey, "WINDOW")
    if fill is not None:
        fill.OverallWidth = float(o.width)
        fill.OverallHeight = float(hi - lo)
        if void is not None:
            ifc.fill(void, fill)


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
        for i, p in enumerate(_polys(plan.columns)):
            ifc.element("IfcColumn", f"Колонна {i + 1}", ifc.solids(p, e, top), st, "COLUMN")
        ifc.element("IfcSlab", "Перекрытие", ifc.solids(plan.footprint, e - slab_t, e), st, "FLOOR")
        # Walls are full-height solids *through* their openings; each door /
        # window gets an IfcOpeningElement voiding its host wall and fills it
        # (IfcRelVoidsElement + IfcRelFillsElement), as BIM tools expect.
        # A passage (no leaf, no lintel) stays a plain gap between walls.
        parts = {"wall": plan.wall_parts.get("wall", plan.walls), "partition": plan.wall_parts.get("partition")}
        hosted = {"wall": [], "partition": []}
        for o in plan.openings:
            if o.kind not in ("door", "window", "vitrage"):
                continue
            probe = o.poly.buffer(0.03)
            area = {k: (probe.intersection(g).area if g is not None and not g.is_empty else 0.0)
                    for k, g in parts.items()}
            hosted[max(area, key=area.get)].append(o)
        n_wall = {"wall": 0, "partition": 0}
        for cat, predefined, label in (("wall", "SOLIDWALL", "Стена"), ("partition", "PARTITIONING", "Перегородка")):
            g = parts[cat]
            bodies = _polys(unary_union([x for x in [g, *(o.poly for o in hosted[cat])]
                                         if x is not None and not x.is_empty]))
            left = list(hosted[cat])
            for p in bodies:
                n_wall[cat] += 1
                w = ifc.element("IfcWall", f"{label} {n_wall[cat]}", ifc.solids(p, e, top), st, predefined)
                mine = [o for o in left if p.intersects(o.poly.centroid.buffer(0.01))]
                left = [o for o in left if o not in mine]
                for o in mine:
                    _ifc_opening(ifc, o, w, st, e, door_h, sill, head, v_head)
            for o in left:                     # host not found: fill without a void
                _ifc_opening(ifc, o, None, st, e, door_h, sill, head, v_head)
        for i, stair in enumerate(plan.stairs):
            riser = float(b.get("riser", 0.165))
            sol = [s for k, t in enumerate(stair.treads) for s in ifc.solids(t, e, min(e + (k + 1) * riser, top))]
            ifc.element("IfcStair", f"Лестница {i + 1}", sol, st, "STRAIGHT_RUN_STAIR")
        for i, r in enumerate(plan.rooms):
            sp = ifc.element("IfcSpace", str(i + 1), ifc.solids(r.poly, e, top), st, "INTERNAL",
                             {"Qto_SpaceBaseQuantities": {"NetFloorArea": float(r.area)}}, container=False)
            if sp is not None:
                sp.LongName = r.name or None
                ifc.space(sp, st)
    if cfg["building"].get("roof", True) and floors:
        f, plan = floors[-1], plans[-1]
        st = ifc.storey("Кровля", f.elevation + f.height)
        z = f.elevation + f.height
        ifc.element("IfcSlab", "Кровля", ifc.solids(plan.footprint, z - slab_t, z), st, "ROOF")
    ifc.finish()
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
