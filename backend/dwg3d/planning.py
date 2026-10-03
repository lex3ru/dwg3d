"""Placing and checking for AI agents: where catalog items fit in a room, a
row of items, how much of a room the cameras see. The results are operations
of viewdata.apply (the agent proposes or applies them), computed with the
conventions of the viewer (frontend/src/furniture/geom.ts):

  u = (cos a, sin a)    the item's width axis
  f = (sin a, -cos a)   its front: the service zone `clear` lies in front,
                        a camera looks along it
  footprint: w along u, d along f, centred at `at`

An item must stand inside its room (the room outlines stand for the walls),
clear of the other items' footprints, of partitions and columns, and of the
doors: the way through an opening with DOOR_CLEAR in front of it on both
sides, and the swing of each leaf (as the viewer's checks do; from the
floor's plan in the file store). Its service zone must be inside the room and
free too. Camera views are sectors cut by the camera's own room (walls between
rooms block the view; doors, partitions inside a room and furniture are not
taken into account — the viewer computes the exact view).
"""
from __future__ import annotations

import math

from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CatalogItem, Floor, LayerObject, Room
from .rooms import polygon

WHERE = ("along_wall", "center", "corners", "grid")
WALL_GAP = 0.01                 # between an item's back and the wall
DOOR_CLEAR = 0.6                # free depth in front of a doorway on each side (as the viewer)
MAX_ITEMS = 200


class PlanError(ValueError):
    """Cannot plan this (bad room, item...)."""


# -------------------------------------------------------------- geometry ---
def axes(angle: float) -> tuple[tuple[float, float], tuple[float, float]]:
    a = math.radians(angle)
    return (math.cos(a), math.sin(a)), (math.sin(a), -math.cos(a))


def facing(nx: float, ny: float) -> float:
    """The angle at which an item's front points along (nx, ny)."""
    return round(math.degrees(math.atan2(nx, -ny)) % 360, 2)


def _rect(cx: float, cy: float, angle: float, hu: float, hf: float) -> Polygon:
    (ux, uy), (fx, fy) = axes(angle)
    return Polygon([(cx + ux * hu * su + fx * hf * sf, cy + uy * hu * su + fy * hf * sf)
                    for su, sf in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


def footprint(at, angle: float, w: float, d: float) -> Polygon:
    return _rect(at[0], at[1], angle, w / 2, d / 2)


def service_zone(at, angle: float, w: float, d: float, clear: float) -> Polygon | None:
    if not clear:
        return None
    _, (fx, fy) = axes(angle)
    k = d / 2 + clear / 2
    return _rect(at[0] + fx * k, at[1] + fy * k, angle, w / 2, clear / 2)


# ------------------------------------------------------------------- data ---
def item_size(o: LayerObject, ci: CatalogItem | None) -> tuple[float, float, float]:
    if o.size:
        return tuple(o.size)                # type: ignore[return-value]
    return (ci.w, ci.d, ci.h) if ci else (0.5, 0.5, 0.5)


def is_high(o: LayerObject | None, ci: CatalogItem | None) -> bool:
    """Mounted at 1 m or higher (cameras, detectors, signs): does not stand in a door's
    way nor on the floor among the furniture (as the viewer's checks)."""
    elev = o.elev if o is not None and o.elev is not None else (ci.elev if ci else None)
    return (elev or 0) >= 1


def is_flat(ci: CatalogItem | None) -> bool:
    return bool(ci) and ci.kind == "zone"


def floor_items(s: Session, floor_id: int) -> list[tuple[LayerObject, CatalogItem | None]]:
    rows = list(s.scalars(select(LayerObject).where(LayerObject.floor_id == floor_id, LayerObject.geom == "point")))
    cat = {c.id: c for c in s.scalars(select(CatalogItem).where(CatalogItem.id.in_({r.item_id for r in rows if r.item_id})))}
    return [(r, cat.get(r.item_id)) for r in rows]


def room_of(s: Session, did: str, rid: int) -> tuple[Room, Floor, Polygon]:
    row = s.execute(select(Room, Floor).join(Floor, Floor.id == Room.floor_id)
                    .where(Room.id == rid, Room.drawing_id == did, Room.idx.is_not(None))).first()
    if row is None or row[1].candidate is None:
        raise PlanError(f"помещение {rid} не найдено на текущих этажах чертежа: см. list_rooms")
    poly = polygon(row[0].poly)
    if poly is None or poly.is_empty or poly.area < 0.5:
        raise PlanError(f"у помещения {rid} нет контура")
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return row[0], row[1], poly


def catalog_item(s: Session, iid: str) -> CatalogItem:
    ci = s.get(CatalogItem, iid)
    if ci is None or not ci.active:
        raise PlanError(f"позиции «{iid}» нет в каталоге: см. search_catalog")
    return ci


def _swing(hinge, tip, center) -> Polygon:
    r = math.dist(hinge, tip)
    a0 = math.atan2(tip[1] - hinge[1], tip[0] - hinge[0])
    da = math.atan2(center[1] - hinge[1], center[0] - hinge[0]) - a0
    da = (da + math.pi) % (2 * math.pi) - math.pi
    return Polygon([tuple(hinge)] + [(hinge[0] + r * math.cos(a0 + da * i / 6), hinge[1] + r * math.sin(a0 + da * i / 6))
                                     for i in range(7)])


def plan_obstacles(s: Session, did: str, floor: Floor) -> tuple[list[Polygon], list[Polygon]]:
    """(partitions and columns, door ways and swings) of the floor from its plan
    in the file store; empty when the plan cannot be read."""
    import json

    from . import files
    from .models import Build, Drawing

    d = s.get(Drawing, did)
    b = s.get(Build, (did, d.current_build)) if d and d.current_build else None
    meta = next((f for f in ((b.result or {}).get("floors") or []) if f.get("id") == floor.candidate), None) if b else None
    try:
        raw = files.store().get_bytes(files.drawing_key(did, f"{b.out_dir}/{meta['plan']}")) if meta and meta.get("plan") else None
        plan = json.loads(raw) if raw else None
    except Exception:
        plan = None
    return obstacles_from_plan(plan) if plan else ([], [])


def obstacles_from_plan(plan: dict) -> tuple[list[Polygon], list[Polygon]]:
    """(partitions and columns, door ways and swings) of a floor's plan (pipeline output)."""
    solids = [g for rings in (plan.get("partitions") or []) + (plan.get("columns") or [])
              if (g := polygon(rings)) is not None and not g.is_empty]
    doors = []
    for o in plan.get("openings") or []:
        if o.get("kind") == "window":
            continue
        ring = (o.get("poly") or [[]])[0]
        if len(ring) >= 4:
            a, b2, c = ring[0], ring[1], ring[2]
            e1, e2 = math.dist(a, b2), math.dist(b2, c)
            along, across = ((b2[0] - a[0], b2[1] - a[1]), (c[0] - b2[0], c[1] - b2[1])) if e1 >= e2 else \
                ((c[0] - b2[0], c[1] - b2[1]), (b2[0] - a[0], b2[1] - a[1]))
            la, lc = math.hypot(*along) or 1, math.hypot(*across) or 1
            ang = math.degrees(math.atan2(along[1], along[0]))      # u along the opening
            doors.append(_rect(o["center"][0], o["center"][1], ang, max(0.05, la / 2 - 0.02), lc / 2 + DOOR_CLEAR))
        for hinge, tip in o.get("leaves") or []:
            doors.append(_swing(hinge, tip, o["center"]))
    return solids, [g for g in doors if g.is_valid and g.area > 1e-4]


# -------------------------------------------------------------- placing ---
class Fitter:
    """Free places in a room: inside the outline, clear of the footprints
    standing there and of what was placed so far (service zones included)."""

    def __init__(self, room: Polygon, taken: list[Polygon], w: float, d: float, clear: float, gap: float):
        self.room = room.buffer(0.02)
        self.taken = [t for t in taken if t.intersects(self.room)]
        self.zones: list[Polygon] = []          # service zones of what is placed now: kept free too
        self.w, self.d, self.clear, self.gap = w, d, clear, gap

    def fits(self, at, angle: float) -> bool:
        fp = footprint(at, angle, self.w, self.d)
        if not self.room.contains(fp):
            return False
        zone = service_zone(at, angle, self.w, self.d, self.clear)
        if zone is not None and not self.room.contains(zone):
            return False
        grown = fp.buffer(self.gap / 2) if self.gap else fp
        for t in self.taken:
            if grown.intersection(t).area > 1e-4 or (zone is not None and zone.intersection(t).area > 1e-4):
                return False
        if any(fp.intersection(z).area > 1e-4 for z in self.zones):
            return False
        return True

    def take(self, at, angle: float):
        self.taken.append(footprint(at, angle, self.w, self.d).buffer(self.gap / 2) if self.gap else
                          footprint(at, angle, self.w, self.d))
        if (z := service_zone(at, angle, self.w, self.d, self.clear)) is not None:
            self.zones.append(z)


def _frame(poly: Polygon) -> tuple[float, tuple[float, float]]:
    """The room's main direction (deg; of its longest side of the minimum rectangle) and centre."""
    rect = poly.minimum_rotated_rectangle
    pts = list(rect.exterior.coords)[:4]
    sides = [(pts[i], pts[(i + 1) % 4]) for i in range(4)]
    (ax, ay), (bx, by) = max(sides, key=lambda e: math.dist(*e))
    c = poly.representative_point()
    return math.degrees(math.atan2(by - ay, bx - ax)), (c.x, c.y)


def _along_wall(fit: Fitter, room: Polygon, count: int, corners_only: bool = False) -> list[tuple]:
    """Backs to the walls: along each side of the room, or into its corners."""
    out = []
    inset = room.buffer(-(fit.d / 2 + WALL_GAP), join_style=2)
    rings = [g for g in getattr(inset, "geoms", [inset]) if not g.is_empty]
    for ring in rings:
        ring = orient(ring, 1.0)
        pts = list(ring.exterior.coords)[:-1]
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            L = math.dist(a, b)
            if L < 1e-6:
                continue
            tx, ty = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            angle = facing(-ty, tx)                     # the room is on the left of a CCW side
            # from this corner along the side: the first place sits w/2 off the corner (d/2 is already off)
            first = max(fit.w / 2 - fit.d / 2, 0) + 0.005
            cands = [first] if corners_only else \
                [first + k * (fit.w + fit.gap) for k in range(int((L - first + fit.w / 2) // (fit.w + fit.gap)) + 1)]
            for s in cands:
                if s > L + 1e-6:
                    break
                at = (round(a[0] + tx * s, 3), round(a[1] + ty * s, 3))
                if fit.fits(at, angle):
                    fit.take(at, angle)
                    out.append((at, angle))
                    if len(out) >= count:
                        return out
    return out


def _grid(fit: Fitter, room: Polygon, count: int, from_center: bool) -> list[tuple]:
    """Rows along the room's main direction, all facing the same way; nearest to the centre first."""
    main, (cx, cy) = _frame(room)
    angle = round((main + 180) % 360, 2)                # width along the main direction
    (ux, uy), (fx, fy) = axes(angle)
    su, sf = fit.w + fit.gap, fit.d + fit.clear + fit.gap
    minx, miny, maxx, maxy = room.bounds
    reach = math.hypot(maxx - minx, maxy - miny)
    cands = []
    for i in range(-int(reach / su) - 1, int(reach / su) + 2):
        for j in range(-int(reach / sf) - 1, int(reach / sf) + 2):
            x, y = cx + ux * su * i + fx * sf * j, cy + uy * su * i + fy * sf * j
            if room.contains(Point(x, y)):
                cands.append((math.hypot(x - cx, y - cy) if from_center else (j, i), (round(x, 3), round(y, 3))))
    out = []
    for _, at in sorted(cands):
        if fit.fits(at, angle):
            fit.take(at, angle)
            out.append((at, angle))
            if len(out) >= count:
                break
    return out


def place_in_room(s: Session, did: str, rid: int, iid: str, count: int, where: str, gap: float) -> dict:
    """Places for `count` items in the room: {floor, room, item, places: [{at, angle}], notes}."""
    if where not in WHERE:
        raise PlanError(f"where: {', '.join(WHERE)}")
    if not 1 <= count <= MAX_ITEMS:
        raise PlanError(f"count: от 1 до {MAX_ITEMS}")
    room, floor, poly = room_of(s, did, rid)
    ci = catalog_item(s, iid)
    high, flat = is_high(None, ci), is_flat(ci)
    # what the item may not stand on: the other items at its level, partitions, columns, door ways
    taken = [footprint((o.x, o.y), o.angle, *item_size(o, c)[:2]) for o, c in floor_items(s, floor.id)
             if not flat and not is_flat(c) and is_high(o, c) == high]
    solids, doors = plan_obstacles(s, did, floor)
    fit = Fitter(poly, taken + ([] if flat else solids) + ([] if high or flat else doors),
                 ci.w, ci.d, ci.clear or 0.0, max(gap, 0.0))
    if where == "along_wall":
        places = _along_wall(fit, poly, count)
    elif where == "corners":
        places = _along_wall(fit, poly, count, corners_only=True)
    else:
        places = _grid(fit, poly, count, from_center=where == "center")
    notes = []
    if len(places) < count:
        notes.append(f"поместилось {len(places)} из {count}: в помещении нет места"
                     + (" у стен" if where in ("along_wall", "corners") else "")
                     + (f" (с зоной обслуживания {ci.clear} м перед предметом)" if ci.clear else ""))
    return {"floor": floor.candidate, "room": {"id": room.id, "name": room.name or "", "area": round(room.area, 2)},
            "item": {"id": ci.id, "name": ci.name, "size": [ci.w, ci.d, ci.h], "clear": ci.clear},
            "places": [{"at": list(at), "angle": angle} for at, angle in places], "notes": notes}


def place_row(s: Session, did: str, floor: Floor, iid: str, start, end, count: int | None, step: float | None,
              angle: float | None) -> dict:
    """Items evenly from start to end (count, or every `step` m); turned along the row unless `angle`."""
    ci = catalog_item(s, iid)
    L = math.dist(start, end)
    if L < 1e-3:
        if count not in (None, 1):
            raise PlanError("start и end совпадают")
        count = 1
    if count is None:
        if not step or step <= 0:
            raise PlanError("задайте count или step")
        count = int(L // step) + 1
    if not 1 <= count <= MAX_ITEMS:
        raise PlanError(f"предметов в ряду: от 1 до {MAX_ITEMS}")
    tx, ty = ((end[0] - start[0]) / L, (end[1] - start[1]) / L) if L >= 1e-3 else (1.0, 0.0)
    ang = round(math.degrees(math.atan2(ty, tx)) % 360, 2) if angle is None else angle % 360
    k = [0.0] if count == 1 else [i / (count - 1) for i in range(count)]
    places = [{"at": [round(start[0] + (end[0] - start[0]) * t, 3), round(start[1] + (end[1] - start[1]) * t, 3)],
               "angle": ang} for t in k]
    # what overlaps: told, not refused (a row is the agent's explicit wish)
    rooms = [(r, polygon(r.poly)) for r in s.scalars(select(Room).where(Room.floor_id == floor.id, Room.idx.is_not(None)))]
    taken = [(o, footprint((o.x, o.y), o.angle, *item_size(o, c)[:2])) for o, c in floor_items(s, floor.id)]
    solids, doors = plan_obstacles(s, did, floor)
    notes = []
    for i, p in enumerate(places):
        fp = footprint(p["at"], p["angle"], ci.w, ci.d)
        hits = [o.id for o, t in taken if fp.intersection(t).area > 1e-4]
        if hits:
            notes.append(f"№{i + 1}: пересекается с {', '.join(hits[:3])}")
        if any(fp.intersection(g).area > 1e-4 for g in doors) and not is_high(None, ci) and not is_flat(ci):
            notes.append(f"№{i + 1}: мешает двери или проходу")
        if any(fp.intersection(g).area > 1e-4 for g in solids):
            notes.append(f"№{i + 1}: стоит на перегородке или колонне")
        if not any(rp is not None and rp.buffer(0.02).contains(fp) for _, rp in rooms):
            notes.append(f"№{i + 1}: не целиком в одном помещении (задевает стену?)")
    return {"floor": floor.candidate, "item": {"id": ci.id, "name": ci.name, "size": [ci.w, ci.d, ci.h]},
            "places": places, "notes": notes}


# ------------------------------------------------------------- coverage ---
def camera_params(o: LayerObject, ci: CatalogItem | None) -> tuple[float, float, float] | None:
    cam = ci.camera if ci else None
    if not cam:
        return None
    props = o.props or {}
    fov = float(props.get("fov") or cam.get("fov") or 90)
    rng = float(props.get("range") or cam.get("range") or 10)
    ident = min(rng, float(cam.get("ident") or rng) * (rng / float(cam.get("range") or rng)))
    return fov, rng, ident


def sector(apex, angle: float, fov: float, r: float) -> Polygon:
    _, (fx, fy) = axes(angle)
    if fov >= 360:
        return Point(apex).buffer(r, 64)
    a0 = math.atan2(fy, fx) - math.radians(fov) / 2
    n = max(8, int(fov))
    pts = [tuple(apex)] + [(apex[0] + r * math.cos(a0 + math.radians(fov) * i / n),
                            apex[1] + r * math.sin(a0 + math.radians(fov) * i / n)) for i in range(n + 1)]
    return Polygon(pts)


def camera_coverage(s: Session, floor: Floor, rid: int | None = None, layers: set[str] | None = None) -> dict:
    """Per room of the floor (or one room): the share of its floor area seen by the
    cameras standing in it, and seen well enough to identify a face; the largest
    unseen parts (bounding boxes)."""
    rooms = [(r, p) for r in s.scalars(select(Room).where(Room.floor_id == floor.id, Room.idx.is_not(None)))
             if (p := polygon(r.poly)) is not None and not p.is_empty and (rid is None or r.id == rid)]
    if rid is not None and not rooms:
        raise PlanError(f"помещение {rid} не найдено на этаже {floor.candidate}")
    cams = []
    for o, ci in floor_items(s, floor.id):
        if layers is not None and o.layer_id not in layers:
            continue
        if (prm := camera_params(o, ci)) is not None:
            cams.append((o, ci, prm))
    out = []
    for r, poly in rooms:
        mine = [(o, ci, prm) for o, ci, prm in cams if poly.buffer(0.05).contains(Point(o.x, o.y))]
        seen = unary_union([sector((o.x, o.y), o.angle, prm[0], prm[1]).intersection(poly) for o, ci, prm in mine]) \
            if mine else Polygon()
        ident = unary_union([sector((o.x, o.y), o.angle, prm[0], prm[2]).intersection(poly) for o, ci, prm in mine]) \
            if mine else Polygon()
        gaps = poly.difference(seen)
        parts = sorted(getattr(gaps, "geoms", [gaps]), key=lambda g: -g.area)
        area = poly.area or 1.0
        out.append({"room": r.id, "name": r.name or "", "area": round(poly.area, 2), "cameras": [o.id for o, _, _ in mine],
                    "seen": round(seen.area / area * 100, 1), "identify": round(ident.area / area * 100, 1),
                    "unseen": [{"area": round(g.area, 2), "bbox": [round(v, 2) for v in g.bounds]}
                               for g in parts[:3] if g.area >= 0.5]})
    return {"floor": floor.candidate, "cameras": len(cams), "rooms": out,
            "note": "приближённо: обзор режут только стены между помещениями; точный расчёт — во вьювере"}
