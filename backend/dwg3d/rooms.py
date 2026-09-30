"""Rooms that keep their id across builds, and which room an object stands in.

After each build the rooms of every floor are matched to the rows of the
previous build (by outline overlap, a matching name counts extra), so a
room keeps its id when the drawing is rebuilt or a new revision is
uploaded; objects and routes refer to it by that id. A room that is not
found any more keeps its row (idx NULL) with its last outline.
"""
from __future__ import annotations

import re

from shapely.geometry import Point, Polygon
from shapely.validation import make_valid
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .models import Floor, LayerObject, Room

NODE_RE = re.compile(r"^floor_(.+)_room_(\d+)$")
MIN_IOU, MIN_IOU_SAME_NAME = 0.5, 0.2


def polygon(rings) -> Polygon | None:
    try:
        p = Polygon(rings[0], rings[1:])
        return p if p.is_valid else make_valid(p)
    except Exception:
        return None


def _shift(rings, dx: float, dy: float) -> list:
    return [[[x + dx, y + dy] for x, y in ring] for ring in rings]


def _iou(a, b) -> float:
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    return inter / max(a.union(b).area, 1e-9) if inter else 0.0


def sync(s: Session, did: str, result: dict, plans: dict[str, dict],
         moves: dict[int, tuple[float, float, float]]) -> None:
    """Match the rooms of the build `result` (outlines from `plans`: the plan
    JSON of each floor by candidate id) to the drawing's room rows, moving
    rows of floors that moved by `moves` (floor row id -> dx, dy, dz, see
    store.sync_floors). Writes the room ids into result["floors"][*]["rooms"]."""
    floors = {f.candidate: f for f in s.scalars(select(Floor).where(Floor.drawing_id == did)) if f.candidate}
    rows = list(s.scalars(select(Room).where(Room.drawing_id == did)))
    for r in rows:
        dx, dy, _ = moves.get(r.floor_id, (0.0, 0.0, 0.0))
        if dx or dy:
            r.poly = _shift(r.poly, dx, dy)
        r.idx = None
    s.flush()
    by_floor: dict[int, list[Room]] = {}
    for r in rows:
        by_floor.setdefault(r.floor_id, []).append(r)

    for fmeta in result.get("floors") or []:
        f = floors.get(fmeta["id"])
        plan = plans.get(fmeta["id"])
        if f is None or plan is None:
            continue
        types = {}
        for m in fmeta.get("rooms") or []:
            if (mt := NODE_RE.match(m.get("node", ""))) and mt.group(1) == fmeta["id"]:
                types[int(mt.group(2))] = m.get("type")
        new = [(i, r, polygon(r["poly"])) for i, r in enumerate(plan.get("rooms") or []) if r.get("poly")]
        old = [(r, polygon(r.poly)) for r in by_floor.get(f.id, [])]
        pairs = []
        for i, nr, npoly in new:
            for orow, opoly in old:
                iou = _iou(npoly, opoly)
                same = bool(nr.get("name")) and nr.get("name") == orow.name
                if iou >= MIN_IOU or (same and iou >= MIN_IOU_SAME_NAME):
                    pairs.append((iou + (0.5 if same else 0.0), i, orow))
        pairs.sort(key=lambda p: -p[0])
        taken_new, taken_old, match = set(), set(), {}
        for _, i, orow in pairs:
            if i in taken_new or orow.id in taken_old:
                continue
            taken_new.add(i)
            taken_old.add(orow.id)
            match[i] = orow
        for i, nr, _ in new:
            row = match.get(i)
            if row is None:
                row = Room(drawing_id=did, floor_id=f.id)
                s.add(row)
            row.idx, row.name, row.type = i, nr.get("name") or "", types.get(i)
            row.area, row.poly = float(nr.get("area") or 0.0), nr["poly"]
        s.flush()
        ids = {r.idx: r.id for r in s.scalars(select(Room).where(Room.floor_id == f.id, Room.idx.is_not(None)))}
        for m in fmeta.get("rooms") or []:
            if (mt := NODE_RE.match(m.get("node", ""))) and int(mt.group(2)) in ids:
                m["id"] = ids[int(mt.group(2))]


class Locator:
    """Which current room of a floor contains a point (outlines loaded once per floor)."""

    def __init__(self, s: Session):
        self.s = s
        self.cache: dict[int, list[tuple[int, Polygon]]] = {}

    def room(self, floor_id: int | None, x: float, y: float) -> int | None:
        if floor_id is None:
            return None
        if floor_id not in self.cache:
            q = select(Room.id, Room.poly).where(Room.floor_id == floor_id, Room.idx.is_not(None))
            self.cache[floor_id] = [(rid, p) for rid, rings in self.s.execute(q)
                                    if (p := polygon(rings)) is not None]
        pt = Point(x, y)
        hits = [(p.area, rid) for rid, p in self.cache[floor_id] if p.covers(pt)]
        return min(hits)[1] if hits else None          # the smallest room around the point


def relocate(s: Session, did: str):
    """Recompute the room of every object of the drawing (after a rebuild)."""
    loc = Locator(s)
    for oid, pid, fid, x, y, rid in s.execute(select(LayerObject.id, LayerObject.project_id, LayerObject.floor_id,
                                                     LayerObject.x, LayerObject.y, LayerObject.room_id)
                                              .where(LayerObject.drawing_id == did)):
        new = loc.room(fid, x, y)
        if new != rid:
            s.execute(update(LayerObject).where(LayerObject.project_id == pid, LayerObject.id == oid)
                      .values(room_id=new))


def rooms_json(s: Session, did: str) -> list[dict]:
    q = (select(Room, Floor.candidate).join(Floor, Floor.id == Room.floor_id)
         .where(Room.drawing_id == did).order_by(Floor.level, Room.floor_id, Room.idx))
    return [{"id": r.id, "floor": cand or "", "idx": r.idx, "name": r.name, "type": r.type, "area": r.area}
            for r, cand in s.execute(q)]


def backfill(s: Session, did: str) -> int:
    """Rooms for the current build of a drawing built before rooms had rows
    (plans read from the file store); the build result gets the room ids.
    Returns the number of rooms."""
    import json

    from sqlalchemy.orm.attributes import flag_modified

    from . import files
    from .models import Build, Drawing

    d = s.get(Drawing, did)
    b = s.get(Build, (did, d.current_build)) if d and d.current_build else None
    if b is None:
        return 0
    result = b.result
    plans = {}
    for f in result.get("floors") or []:
        raw = files.store().get_bytes(files.drawing_key(did, f"out/{f['plan']}")) if f.get("plan") else None
        if raw:
            plans[f["id"]] = json.loads(raw)
    sync(s, did, result, plans, {})
    relocate(s, did)
    b.result = result
    flag_modified(b, "result")
    return s.scalar(select(func.count()).select_from(Room).where(Room.drawing_id == did, Room.idx.is_not(None)))
