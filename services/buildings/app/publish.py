"""Making a finished build of a drawing the state of the building.

Floors are matched to the floors already known by the sheet of the drawing
they are on, rooms by the overlap of their outlines (the same name counts
extra) — so a floor and a room keep their ids from build to build, and
whatever refers to them stays attached. What is not found any more is not
deleted but retired.

Two steps: `propose` says what a build would do (which floor and room of the
build continues which known one, what would be retired) without changing
anything; `apply` does it. The proposal is what a draft revision keeps and an
administrator corrects before publishing.
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

from .models import comments, drawings, floor_plans, floors, revisions, rooms

NODE_RE = re.compile(r"^floor_(.+)_room_(\d+)$")
SHEET_MIN_IOU = 0.5
ROOM_MIN_IOU, ROOM_MIN_IOU_SAME_NAME = 0.5, 0.2
MERGED_MIN_COVER = 0.9          # a known room this much inside a room of the build was merged into it (a wall erased)


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


def _cover(outer, inner) -> float:
    """How much of `inner` lies inside `outer`."""
    if outer is None or inner is None or outer.is_empty or inner.is_empty or inner.area <= 0:
        return 0.0
    return outer.intersection(inner).area / inner.area


def absorb(new: list[dict], old: list, matched: dict[int, object]) -> None:
    """A room of the build no known room continues, but which holds known rooms whole (a partition between them
    erased), continues the largest of them; `matched` is completed in place."""
    taken = {row.id for row in matched.values()}
    for i, r in enumerate(new):
        if i in matched:
            continue
        outer = polygon(r["poly"])
        inside = [row for row in old
                  if row.id not in taken and _cover(outer, polygon(row.polygon)) >= MERGED_MIN_COVER]
        if inside:
            heir = max(inside, key=lambda row: row.area)
            matched[i] = heir
            taken.add(heir.id)


def merges(proposal: dict, plans: dict[str, dict], by_floor: dict[UUID, list]) -> dict[str, str]:
    """Known rooms the build does not continue but which lie whole inside a room it does: id -> the heir's id.
    These are merged into the heir — what was in them goes there — rather than retired."""
    used = {r["room_id"] for r in proposal["rooms"] if r["room_id"]}
    of_floor = {f["candidate"]: f["floor_id"] for f in proposal["floors"]}
    heirs: dict[str, list] = {}
    for r in proposal["rooms"]:
        poly = next((x["poly"] for i, x in _plan_rooms(plans.get(r["candidate"])) if i == r["idx"]), None)
        if r["room_id"] and poly and of_floor.get(r["candidate"]):
            heirs.setdefault(of_floor[r["candidate"]], []).append((r["room_id"], polygon(poly)))
    out = {}
    for fid, rows in by_floor.items():
        for row in rows:
            if row.status != "active" or str(row.id) in used:
                continue
            inner = polygon(row.polygon)
            best = max(heirs.get(str(fid), []), key=lambda h: _cover(h[1], inner), default=None)
            if best is not None and _cover(best[1], inner) >= MERGED_MIN_COVER:
                out[str(row.id)] = best[0]
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


# ---------------------------------------------------------------- propose ---
async def _known(session: AsyncSession, drawing_id: UUID) -> tuple[list, list]:
    """The drawing's floors (matched first by their place in the last build) and their rooms; rooms merged
    into others are not candidates any more."""
    floor_rows = (await session.execute(select(floors).where(floors.c.drawing_id == drawing_id)
                                        .order_by(floors.c.candidate.is_(None), floors.c.id))).all()
    room_rows = (await session.execute(select(rooms).where(
        rooms.c.floor_id.in_([r.id for r in floor_rows] or [uuid7()]), rooms.c.merged_into.is_(None)))).all()
    return floor_rows, room_rows


def _plan_rooms(plan: dict | None) -> list[tuple[int, dict]]:
    return [(i, r) for i, r in enumerate((plan or {}).get("rooms") or []) if r.get("poly")]


async def propose(session: AsyncSession, drawing, result: dict, plans: dict[str, dict]) -> dict:
    """What the build would do, nothing changed: {floors, moves, rooms} — each floor of the build with the known
    floor it continues (or none), each room of the build with the known room it continues (or none)."""
    new_floors = [f for f in result.get("floors") or [] if f.get("bbox")]
    sheets = [SimpleNamespace(id=f["id"], space=f.get("space", "Model"), owner=f.get("owner"), bbox=f["bbox"])
              for f in new_floors]
    floor_rows, room_rows = await _known(session, drawing.id)
    taken: dict[str, object] = {}
    for row in floor_rows:
        hit = match_sheet(row.anchor, [s for s in sheets if s.id not in taken], prefer_id=row.candidate)
        if hit is not None:
            taken[hit.id] = row
    moves: dict[str, list[float]] = {}
    out_floors = []
    for f in new_floors:
        row = taken.get(f["id"])
        if row is not None:
            ox, oy = row.anchor.get("offset") or (0.0, 0.0)
            nx, ny = f.get("offset") or (0.0, 0.0)
            moves[str(row.id)] = [nx - ox, ny - oy]
        out_floors.append({"candidate": f["id"], "floor_id": str(row.id) if row is not None else None,
                           "name": f.get("name") or "", "level": f.get("level")})
    by_floor = _shifted(room_rows, moves)
    out_rooms = []
    for f in new_floors:
        row = taken.get(f["id"])
        found = _plan_rooms(plans.get(f["id"]))
        known_here = by_floor.get(row.id, []) if row is not None else []
        matched = match_rooms([r for _, r in found], known_here)
        absorb([r for _, r in found], [k for k in known_here if k.status == "active"], matched)
        for k, (idx, r) in enumerate(found):
            old = matched.get(k)
            out_rooms.append({"candidate": f["id"], "idx": idx, "name": r.get("name") or "",
                              "area": round(float(r.get("area") or 0.0), 2),
                              "room_id": str(old.id) if old is not None else None, "auto": True})
    return {"floors": out_floors, "moves": moves, "rooms": out_rooms}


def _shifted(room_rows: list, moves: dict[str, list[float]]) -> dict[UUID, list]:
    """Known rooms by floor, moved as their floor is aligned in the build."""
    by_floor: dict[UUID, list] = {}
    for row in room_rows:
        dx, dy = moves.get(str(row.floor_id), (0.0, 0.0))
        if dx or dy:
            row = SimpleNamespace(**{**row._mapping, "polygon": _shift(row.polygon, dx, dy)})
        by_floor.setdefault(row.floor_id, []).append(row)
    return by_floor


async def explain(session: AsyncSession, drawing, plans: dict[str, dict], proposal: dict) -> dict:
    """The proposal as differences to look at: each room of the build — new, the same, renamed, with a changed
    outline; the known rooms that would be retired; for each floor, the known rooms one may pick instead."""
    floor_rows, room_rows = await _known(session, drawing.id)
    by_floor = _shifted(room_rows, proposal.get("moves") or {})
    known = {str(r.id): r for rows in by_floor.values() for r in rows}
    of_floor = {f["candidate"]: f["floor_id"] for f in proposal["floors"]}
    polys = {(cand, i): r["poly"] for cand, plan in plans.items() for i, r in _plan_rooms(plan)}
    rooms_out, used = [], set()
    for r in proposal["rooms"]:
        old = known.get(r["room_id"]) if r["room_id"] else None
        changes = []
        if old is None:
            changes = ["new"]
        else:
            used.add(r["room_id"])
            if old.status != "active":
                changes.append("returned")
            if "name" not in old.manual and (r["name"] or "") != (old.name or ""):
                changes.append("name")
            if _iou(polygon(polys.get((r["candidate"], r["idx"])) or [[]]), polygon(old.polygon)) < 0.995:
                changes.append("outline")
        rooms_out.append({**r, "floor_id": of_floor.get(r["candidate"]), "old_name": old.name if old else None,
                          "changes": changes})
    active_floors = {f["floor_id"] for f in proposal["floors"] if f["floor_id"]}
    merged = merges(proposal, plans, by_floor)
    heir_name = {r["room_id"]: r["name"] for r in rooms_out if r["room_id"]}
    gone = [{"id": str(row.id), "name": row.name, "floor_id": str(row.floor_id), "area": round(row.area, 2)}
            for row in room_rows if row.status == "active" and str(row.id) not in used]
    retired = [g for g in gone if g["id"] not in merged]
    merged_out = [{**g, "into": merged[g["id"]], "into_name": heir_name.get(merged[g["id"]], "")}
                  for g in gone if g["id"] in merged]
    floors_retired = [str(f.id) for f in floor_rows if f.status == "active" and str(f.id) not in active_floors]
    choices = {fid: [{"id": str(r.id), "name": r.name, "area": round(r.area, 2)} for r in rows if r.status == "active"]
               for fid, rows in ((str(k), v) for k, v in by_floor.items())}
    count = {"new": sum("new" in r["changes"] for r in rooms_out),
             "same": sum(not r["changes"] for r in rooms_out),
             "changed": sum(bool(r["changes"]) and "new" not in r["changes"] for r in rooms_out),
             "retired": len(retired), "merged": len(merged_out),
             "floors_new": sum(f["floor_id"] is None for f in proposal["floors"]),
             "floors_retired": len(floors_retired)}
    return {"floors": proposal["floors"], "rooms": rooms_out, "retired": retired, "merged": merged_out,
            "floors_retired": floors_retired,
            "choices": choices, "count": count}


def loses_nothing(explained: dict) -> bool:
    """A build that only adds, keeps and merges (partitions erased) — no room or floor retired — needs nobody's
    review."""
    return not explained["retired"] and not explained["floors_retired"]


# ------------------------------------------------------------------ apply ---
async def apply(session: AsyncSession, drawing, build: dict, result: dict, plans: dict[str, dict], proposal: dict,
                revision_id: UUID) -> dict:
    """Make the build the state of the building as the proposal says; returns the summary of what changed."""
    building_id, drawing_id = drawing.building_id, drawing.id
    new_floors = [f for f in result.get("floors") or [] if f.get("bbox")]
    floor_rows, room_rows = await _known(session, drawing_id)
    by_id = {r.id: r for r in floor_rows}
    floor_of = {f["candidate"]: UUID(f["floor_id"]) if f["floor_id"] else None for f in proposal["floors"]}
    room_of = {(r["candidate"], r["idx"]): UUID(r["room_id"]) if r["room_id"] else None for r in proposal["rooms"]}
    moves = proposal.get("moves") or {}

    # ---- floors
    floor_ids: dict[str, UUID] = {}
    summary = {"floors": {"created": [], "retired": []}, "rooms": {"created": [], "changed": [], "retired": []}}
    for row in floor_rows:                                  # ids in the build may swap between floors: clear first
        await session.execute(update(floors).where(floors.c.id == row.id).values(candidate=None))
    for f in new_floors:
        row = by_id.get(floor_of.get(f["id"])) if floor_of.get(f["id"]) else None
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
    known = {row.id: row for rows in _shifted(room_rows, moves).values() for row in rows}
    room_ids: dict[tuple[str, int], UUID] = {}
    kept: set[UUID] = set()
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
        for idx, r in _plan_rooms(plan):
            m = meta.get(idx, {})
            label = {key: m[key] for key in ("label_pos", "label_angle", "label_w", "label_d") if key in m}
            values = {"idx": idx, "area": float(r.get("area") or 0.0), "polygon": r["poly"], "label": label,
                      "status": "active", "retired_at": None, "revision_id": revision_id, "floor_id": fid}
            row = known.get(room_of.get((f["id"], idx)))
            if row is None:
                rid = uuid7()
                await session.execute(insert(rooms).values(id=rid, building_id=building_id,
                                                           name=r.get("name") or "", type=m.get("type"), **values))
                summary["rooms"]["created"].append(str(rid))
            else:
                rid = row.id
                kept.add(rid)
                if "name" not in row.manual:
                    values["name"] = r.get("name") or ""
                if "type" not in row.manual:
                    values["type"] = m.get("type")
                outline = _iou(polygon(r["poly"]), polygon(row.polygon)) < 0.995
                if outline or row.status != "active" or row.floor_id != fid or any(
                        getattr(row, key) != values[key] for key in ("name", "type") if key in values):
                    summary["rooms"]["changed"].append({"id": str(rid), "outline": outline})
                await session.execute(update(rooms).where(rooms.c.id == rid)
                                      .values(**values, version=rooms.c.version + 1))
            room_ids[(f["id"], idx)] = rid
    retired = [row for row in room_rows if row.status == "active" and row.id not in kept]
    merged = merges(proposal, plans, _shifted(room_rows, moves))
    if retired:
        await session.execute(update(rooms).where(rooms.c.id.in_([r.id for r in retired])).values(
            status="retired", retired_at=func.now(), idx=None, version=rooms.c.version + 1))
        summary["rooms"]["retired"] = [str(r.id) for r in retired]
    into: dict[str, list] = {}
    for row in retired:
        if str(row.id) in merged:
            into.setdefault(merged[str(row.id)], []).append(row)
            await session.execute(update(rooms).where(rooms.c.id == row.id)
                                  .values(merged_into=UUID(merged[str(row.id)])))

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

    # a floor aligned differently in this build: what stands on it by a point moves with it
    shifted = {fid: [round(dx, 4), round(dy, 4)] for fid, (dx, dy) in moves.items()
               if (dx or dy) and UUID(fid) in set(floor_ids.values())}
    for fid, (dx, dy) in shifted.items():
        await session.execute(update(comments).where(comments.c.floor_id == UUID(fid), comments.c.x.is_not(None))
                              .values(x=comments.c.x + dx, y=comments.c.y + dy))
    summary["moves"] = shifted
    await emit(session, "buildings.revision.published", ("revision", revision_id),
               {"revision_id": str(revision_id), "drawing_id": str(drawing_id), "build_id": build["id"],
                "floors": {**summary["floors"], "active": [str(i) for i in floor_ids.values()]},
                "rooms": summary["rooms"], "moves": shifted}, building_id=building_id)
    for heir, rows in into.items():               # a partition erased: what was in these rooms goes to the heir
        await emit(session, "buildings.room.merged", ("room", UUID(heir)),
                   {"from": [str(r.id) for r in rows], "into": heir, "floor_id": str(rows[0].floor_id)},
                   building_id=building_id, floor_id=rows[0].floor_id, room_id=UUID(heir))
    for row in retired:
        if str(row.id) in merged:
            continue
        await emit(session, "buildings.room.retired", ("room", row.id),
                   {"room_id": str(row.id), "floor_id": str(row.floor_id)},
                   building_id=building_id, floor_id=row.floor_id, room_id=row.id)
    return summary


async def publish(session: AsyncSession, drawing, build: dict, result: dict, plans: dict[str, dict]) -> dict:
    """Propose and apply at once (the first build of a drawing, or one that loses nothing)."""
    revision_id = uuid7()
    proposal = await propose(session, drawing, result, plans)
    summary = await apply(session, drawing, build, result, plans, proposal, revision_id)
    await session.execute(insert(revisions).values(
        id=revision_id, building_id=drawing.building_id, drawing_id=drawing.id, build_id=UUID(build["id"]),
        n=build["n"], status="published", summary=summary, published_at=func.now()))
    return summary
