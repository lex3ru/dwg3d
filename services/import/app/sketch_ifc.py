"""A drawn plan as IFC4: the pipeline's export (app/dwg/exports.py), with each
wall at its own height and each opening at its own sill and height.

Walls are solids through their openings, each opening an IfcOpeningElement
voiding its wall and filled by a door or a window, as BIM tools expect; a
passage is a void with nothing in it (the wall stays above it). A room's
number names its IfcSpace, its name is the long name.
"""
from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString
from shapely.ops import unary_union

from .dwg.exports import _Ifc
from .dwg.geometry import FloorPlan, _opening_rect, _polys
from .dwg.model3d import _pane


def _opening(ifc, o, wall, storey, e: float, top: float) -> None:
    lo, hi = max(o.sill, 0.0), min(o.head, top - e)
    if hi - lo < 0.01:
        return
    void = None
    if wall is not None:
        void = ifc.element("IfcOpeningElement", o.id, ifc.solids(_opening_rect(o, 0.1), e + lo, e + hi), storey,
                           "OPENING", container=False, rel_to=wall)
        if void is not None:
            ifc.void(void, wall)
    if o.kind == "passage":
        return
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


def export_sketch_ifc(path: Path, floors, plans: list[FloorPlan], cfg: dict, center, name: str = "Здание") -> None:
    b = cfg["building"]
    slab_t = float(b["slab_thickness"])
    ifc = _Ifc(name, center)
    for f, plan in zip(floors, plans, strict=True):
        st = ifc.storey(f.name, f.elevation)
        e = f.elevation
        top = e + f.height - slab_t
        ifc.element("IfcSlab", "Перекрытие", ifc.solids(plan.footprint, e - slab_t, e), st, "FLOOR")
        # the walls by height: up to the ceiling, and the lower ones (plan_of in app/sketch.py)
        groups = [(plan.full_parts["wall"], top, "wall"), (plan.full_parts["partition"], top, "partition")]
        groups += [(g, min(e + h, top), "wall" if role == "walls" else "partition") for g, h, role in plan.low_parts]
        # each opening with the wall it is in: the group it overlaps most, at its own top
        hosted: list[list] = [[] for _ in groups]
        for o in plan.openings:
            probe = o.poly.buffer(0.03)
            area = [probe.intersection(g).area if g is not None and not g.is_empty else 0.0 for g, _, _ in groups]
            hosted[max(range(len(groups)), key=area.__getitem__)].append(o)
        n = {"wall": 0, "partition": 0}
        for (g, z1, cat), mine in zip(groups, hosted, strict=True):
            predefined, label = ("SOLIDWALL", "Стена") if cat == "wall" else ("PARTITIONING", "Перегородка")
            left = list(mine)
            for p in _polys(unary_union([x for x in [g, *(o.poly for o in mine)] if x is not None and not x.is_empty])):
                n[cat] += 1
                w = ifc.element("IfcWall", f"{label} {n[cat]}", ifc.solids(p, e, z1), st, predefined)
                here = [o for o in left if p.intersects(o.poly.centroid.buffer(0.01))]
                left = [o for o in left if o not in here]
                for o in here:
                    _opening(ifc, o, w, st, e, z1)
            for o in left:                     # host not found: the fill without a void
                _opening(ifc, o, None, st, e, z1)
        for i, p in enumerate(_polys(plan.columns)):
            ifc.element("IfcColumn", f"Колонна {i + 1}", ifc.solids(p, e, top), st, "COLUMN")
        for i, stair in enumerate(plan.stairs):             # each flight in its own steps, up to the next floor
            riser = getattr(stair, "riser", float(b.get("riser", 0.165)))
            solids = [s for k, t in enumerate(stair.treads) for s in ifc.solids(t, e, min(e + (k + 1) * riser, top))]
            ifc.element("IfcStair", f"Лестница {i + 1}", solids, st, "STRAIGHT_RUN_STAIR")
        for i, r in enumerate(plan.rooms):
            sp = ifc.element("IfcSpace", getattr(r, "number", "") or str(i + 1), ifc.solids(r.poly, e, top), st,
                             "INTERNAL", {"Qto_SpaceBaseQuantities": {"NetFloorArea": float(r.area)}}, container=False)
            if sp is not None:
                sp.LongName = r.name or None
                ifc.space(sp, st)
    if b.get("roof", True) and floors:
        f, plan = floors[-1], plans[-1]
        st = ifc.storey("Кровля", f.elevation + f.height)
        z = f.elevation + f.height
        ifc.element("IfcSlab", "Кровля", ifc.solids(getattr(plan, "full_footprint", plan.footprint), z - slab_t, z), st,
                    "ROOF")
    ifc.finish()
    ifc.f.write(str(path))
