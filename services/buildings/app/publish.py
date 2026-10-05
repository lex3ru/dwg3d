"""Making a finished build of a drawing the state of the building.

Floors are matched to the floors already known by the sheet of the drawing
they are on, rooms by the overlap of their outlines (the same name counts
extra) — so a floor and a room keep their ids from build to build, and
whatever refers to them stays attached. What is not found any more is not
deleted but retired.

Until revisions can be reviewed before publishing (stage 7) every build is
published as soon as it is finished.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from uuid import UUID

from shapely.geometry import Point, Polygon
from shapely.validation import make_valid
from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import emit, uuid7

from .models import drawings, floor_plans, floors, revisions, rooms

NODE_RE = re.compile(r"^floor_(.+)_room_(\d+)$")
SHEET_MIN_IOU = 0.5
ROOM_MIN_IOU, ROOM_MIN_IOU_SAME_NAME = 0.5, 0.2


# ------------------------------------------------------------------ floors ---
def anchor_of(f: dict) -> dict:
    """What a floor is recognised by: its sheet in the drawing and how it was aligned."""
    return {"id": f["id"], "space": f.get("space", "Model"), "owner": f.get("owner"),
            "bbox": [round(float(v), 3) for v in f["bbox"]], "name": f.get("name", ""),
            "offset": [round(float(v), 4) for v in (f.get("offset") or (0.0, 0.0))]}


def _bbox_iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_sheet(anchor: dict, candidates: list[SimpleNamespace], prefer_id: str | None = None):
    """The floor of a new build an anchor refers to, or None."""
    best, best_score = None, 0.0
    for c in candidates:
        if c.space != anchor.get("space", "Model"):
            continue
        if anchor.get("owner") is not None or c.owner is not None:
            if c.owner != anchor.get("owner"):
                continue
            score = 2.0                                   # the same floor block: exact
        else:
            score = _bbox_iou(c.bbox, anchor["bbox"])
            if score < SHEET_MIN_IOU:
                continue
        score += 1e-3 * (c.id == prefer_id)
        if score > best_score:
            best, best_score = c, score
    return best


# ------------------------------------------------------------------- rooms ---
def polygon(rings) -> Polygon | None:
    try:
        p = Polygon(rings[0], rings[1:])
        return p if p.is_valid else make_valid(p)
    except Exception:
        return None


def _iou(a, b) -> float:
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    return inter / max(a.union(b).area, 1e-9) if inter else 0.0


def _shift(rings, dx: float, dy: float) -> list:
    return [[[x + dx, y + dy] for x, y in ring] for ring in rings]


def match_rooms(new: list[dict], old: list) -> dict[int, object]:
    """index of a new room -> the row it continues. `new`: plan rooms {name, poly}; `old`: rows with name, polygon."""
    new_polys = [(i, r, polygon(r["poly"])) for i, r in enumerate(new)]
    old_polys = [(row, polygon(row.polygon)) for row in old]
    pairs = []
    for i, r, np_ in new_polys:
        for row, op in old_polys:
            iou = _iou(np_, op)
            same = bool(r.get("name")) and r.get("name") == row.name
            if iou >= ROOM_MIN_IOU or (same and iou >= ROOM_MIN_IOU_SAME_NAME):
                pairs.append((iou + (0.5 if same else 0.0), i, row))
    pairs.sort(key=lambda p: -p[0])
    taken_new, taken_old, out = set(), set(), {}
    for _, i, row in pairs:
        if i in taken_new or row.id in taken_old:
            continue
        taken_new.add(i)
        taken_old.add(row.id)
        out[i] = row
    return out


def locate(room_rows: list, points: list[list[float]]) -> list[UUID | None]:
    """The room each point is in (the smallest one around it), or None."""
    polys = [(p.area, row.id, p) for row in room_rows if (p := polygon(row.polygon)) is not None]
    polys.sort(key=lambda t: t[0])
    out = []
    for x, y in points:
        pt = Point(x, y)
        out.append(next((rid for _, rid, p in polys if p.covers(pt)), None))
    return out


# ----------------------------------------------------------------- publish ---
async def publish(session: AsyncSession, drawing, build: dict, result: dict, plans: dict[str, dict]) -> dict:
    """Apply the build to the drawing's floors and rooms; returns the summary of what changed.
    `plans`: the plan JSON of each floor by its id in the build."""
    building_id, drawing_id = drawing.building_id, drawing.id
    revision_id = uuid7()
    new_floors = [f for f in result.get("floors") or [] if f.get("bbox")]
    sheets = [SimpleNamespace(id=f["id"], space=f.get("space", "Model"), owner=f.get("owner"), bbox=f["bbox"])
              for f in new_floors]

    # ---- floors
    floor_rows = (await session.execute(select(floors).where(floors.c.drawing_id == drawing_id)
                                        .order_by(floors.c.candidate.is_(None), floors.c.id))).all()
    taken: dict[str, object] = {}
    for row in floor_rows:
        hit = match_sheet(row.anchor, [s for s in sheets if s.id not in taken], prefer_id=row.candidate)
        if hit is not None:
            taken[hit.id] = row
    floor_ids: dict[str, UUID] = {}
    moves: dict[UUID, tuple[float, float]] = {}
    summary = {"floors": {"created": [], "retired": []}, "rooms": {"created": [], "changed": [], "retired": []}}
    for row in floor_rows:                                  # ids in the build may swap between floors: clear first
        await session.execute(update(floors).where(floors.c.id == row.id).values(candidate=None))
    for f in new_floors:
        row = taken.get(f["id"])
        values = {"anchor": anchor_of(f), "candidate": f["id"], "level": f.get("level"),
                  "elevation": float(f.get("elevation") or 0.0), "height": float(f.get("height") or 0.0),
                  "status": "active", "revision_id": revision_id}
        if row is None:
            fid = uuid7()
            await session.execute(insert(floors).values(id=fid, building_id=building_id, drawing_id=drawing_id,
                                                        name=f.get("name") or "", **values))
            summary["floors"]["created"].append(str(fid))
        else:
            fid = row.id
            ox, oy = row.anchor.get("offset") or (0.0, 0.0)
            nx, ny = f.get("offset") or (0.0, 0.0)
            moves[fid] = (nx - ox, ny - oy)
            if "name" not in row.manual:
                values["name"] = f.get("name") or ""
            await session.execute(update(floors).where(floors.c.id == fid)
                                  .values(**values, version=floors.c.version + 1))
        floor_ids[f["id"]] = fid
    lost_floors = [row.id for row in floor_rows if row.id not in set(floor_ids.values()) and row.status == "active"]
    if lost_floors:
        await session.execute(update(floors).where(floors.c.id.in_(lost_floors))
                              .values(status="retired", version=floors.c.version + 1))
        summary["floors"]["retired"] = [str(i) for i in lost_floors]

    # ---- rooms
    room_rows = (await session.execute(select(rooms).where(
        rooms.c.floor_id.in_([r.id for r in floor_rows] or [uuid7()])))).all()
    by_floor: dict[UUID, list] = {}
    for row in room_rows:
        dx, dy = moves.get(row.floor_id, (0.0, 0.0))
        if dx or dy:                                        # the floor was aligned differently: its rooms moved with it
            row = SimpleNamespace(**{**row._mapping, "polygon": _shift(row.polygon, dx, dy)})
        by_floor.setdefault(row.floor_id, []).append(row)
    retired: list = [row for fid in lost_floors for row in by_floor.get(fid, []) if row.status == "active"]
    room_ids: dict[tuple[str, int], UUID] = {}
    for f in new_floors:
        fid, plan = floor_ids[f["id"]], plans.get(f["id"])
        if plan is None:
            continue
        await session.execute(pg_insert(floor_plans).values(floor_id=fid, revision_id=revision_id, data=plan)
                              .on_conflict_do_update(index_elements=["floor_id"],
                                                     set_={"revision_id": revision_id, "data": plan}))
        meta = {}
        for m in f.get("rooms") or []:
            if (hit := NODE_RE.match(m.get("node", ""))) and hit.group(1) == f["id"]:
                meta[int(hit.group(2))] = m
        new_rooms = [r for r in plan.get("rooms") or [] if r.get("poly")]
        indexes = [i for i, r in enumerate(plan.get("rooms") or []) if r.get("poly")]
        old = by_floor.get(fid, [])
        matched = match_rooms(new_rooms, old)
        for k, r in enumerate(new_rooms):
            idx = indexes[k]
            m = meta.get(idx, {})
            label = {key: m[key] for key in ("label_pos", "label_angle", "label_w", "label_d") if key in m}
            values = {"idx": idx, "area": float(r.get("area") or 0.0), "polygon": r["poly"], "label": label,
                      "status": "active", "retired_at": None, "revision_id": revision_id}
            row = matched.get(k)
            if row is None:
                rid = uuid7()
                await session.execute(insert(rooms).values(id=rid, building_id=building_id, floor_id=fid,
                                                           name=r.get("name") or "", type=m.get("type"), **values))
                summary["rooms"]["created"].append(str(rid))
            else:
                rid = row.id
                if "name" not in row.manual:
                    values["name"] = r.get("name") or ""
                if "type" not in row.manual:
                    values["type"] = m.get("type")
                outline = _iou(polygon(r["poly"]), polygon(row.polygon)) < 0.995
                if outline or row.status != "active" or any(
                        getattr(row, key) != values[key] for key in ("name", "type") if key in values):
                    summary["rooms"]["changed"].append({"id": str(rid), "outline": outline})
                await session.execute(update(rooms).where(rooms.c.id == rid)
                                      .values(**values, version=rooms.c.version + 1))
            room_ids[(f["id"], idx)] = rid
        kept = {row.id for row in matched.values()}
        retired += [row for row in old if row.id not in kept and row.status == "active"]
    if retired:
        await session.execute(update(rooms).where(rooms.c.id.in_([r.id for r in retired])).values(
            status="retired", retired_at=func.now(), idx=None, version=rooms.c.version + 1))
        summary["rooms"]["retired"] = [str(r.id) for r in retired]

    # ---- the result of the build, floors and rooms carrying our ids
    for f in result.get("floors") or []:
        f["floor_id"] = str(floor_ids[f["id"]]) if f["id"] in floor_ids else None
        for m in f.get("rooms") or []:
            if (hit := NODE_RE.match(m.get("node", ""))) and (f["id"], int(hit.group(2))) in room_ids:
                m["id"] = str(room_ids[(f["id"], int(hit.group(2)))])
    for item in (result.get("entrances") or []) + (result.get("pois") or []):
        item["floor_id"] = str(floor_ids[item["floor"]]) if item.get("floor") in floor_ids else None
    await session.execute(update(drawings).where(drawings.c.id == drawing_id).values(
        build_id=UUID(build["id"]), build_n=build["n"], result=result, updated_at=func.now(),
        version=drawings.c.version + 1))
    await session.execute(insert(revisions).values(
        id=revision_id, building_id=building_id, drawing_id=drawing_id, build_id=UUID(build["id"]), n=build["n"],
        status="published", summary=summary, published_at=func.now()))

    await emit(session, "buildings.revision.published", ("revision", revision_id),
               {"revision_id": str(revision_id), "drawing_id": str(drawing_id), "build_id": build["id"],
                "floors": {**summary["floors"], "active": [str(i) for i in floor_ids.values()]},
                "rooms": summary["rooms"]}, building_id=building_id)
    for row in retired:
        await emit(session, "buildings.room.retired", ("room", row.id),
                   {"room_id": str(row.id), "floor_id": str(row.floor_id)},
                   building_id=building_id, floor_id=row.floor_id, room_id=row.id)
    return summary
