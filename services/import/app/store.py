"""Drawings, their files and builds in the database: what the requests and the worker share."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from twin_chassis import Identity, emit, uuid7

from .models import builds, drawing_files, drawings

ACTIVE = ("queued", "running")
# what of a build's result other services may need (the rest is working data of the pipeline)
RESULT_KEYS = ("source", "units", "units_source", "converter", "floors", "roof_node", "height_range", "candidates",
               "triangles", "warnings", "elapsed_s", "center", "exports", "extent", "quality", "edits_unmatched",
               "entrances", "pois", "room_types", "layers")


def iso(t: datetime | None) -> str | None:
    return t.isoformat().replace("+00:00", "Z") if t else None


def build_json(b) -> dict:
    return {"id": str(b.id), "drawing_id": str(b.drawing_id), "n": b.n, "status": b.status, "stage": b.stage,
            "progress": round(b.progress, 3), "message": b.message, "error": b.error,
            "created_at": iso(b.created_at), "started_at": iso(b.started_at), "finished_at": iso(b.finished_at)}


async def latest_build(session: AsyncSession, drawing_id: UUID):
    return (await session.execute(select(builds).where(builds.c.drawing_id == drawing_id)
                                  .order_by(builds.c.n.desc()).limit(1))).one_or_none()


async def has_active_build(session: AsyncSession, drawing_id: UUID) -> bool:
    return (await session.execute(select(builds.c.id).where(builds.c.drawing_id == drawing_id,
                                                            builds.c.status.in_(ACTIVE)).limit(1))).first() is not None


async def drawing_json(session: AsyncSession, d) -> dict:
    """A drawing as the requests answer: with its current file and the state of its latest build."""
    f = (await session.execute(select(drawing_files).where(drawing_files.c.id == d.current_file_id))).one_or_none()
    b = await latest_build(session, d.id)
    return {
        "id": str(d.id), "building_id": str(d.building_id), "name": d.name or (f.filename if f else ""),
        "filename": f.filename if f else None, "size": f.size if f else None, "file_n": f.n if f else None,
        "build": build_json(b) if b else None,
        "current_build_id": str(d.current_build_id) if d.current_build_id else None,
        "created_at": iso(d.created_at), "updated_at": iso(d.updated_at),
    }


async def get_drawing(session: AsyncSession, drawing_id: UUID, *, lock: bool = False):
    q = select(drawings).where(drawings.c.id == drawing_id, drawings.c.deleted_at.is_(None))
    return (await session.execute(q.with_for_update() if lock else q)).one_or_none()


async def add_file(session: AsyncSession, drawing_id: UUID, *, file_id: UUID, filename: str, size: int, sha256: str,
                   storage_key: str, me: Identity):
    n = (await session.execute(select(func.coalesce(func.max(drawing_files.c.n), 0))
                               .where(drawing_files.c.drawing_id == drawing_id))).scalar_one() + 1
    await session.execute(insert(drawing_files).values(
        id=file_id, drawing_id=drawing_id, n=n, filename=filename, size=size, sha256=sha256,
        storage_key=storage_key, uploaded_by=me.sub))
    await session.execute(update(drawings).where(drawings.c.id == drawing_id)
                          .values(current_file_id=file_id, updated_at=func.now()))


async def enqueue(session: AsyncSession, d, me: Identity | None, file_id: UUID | None = None) -> UUID:
    """A new build of the drawing's current file, queued for the worker."""
    n = (await session.execute(select(func.coalesce(func.max(builds.c.n), 0))
                               .where(builds.c.drawing_id == d.id))).scalar_one() + 1
    build_id = uuid7()
    await session.execute(insert(builds).values(
        id=build_id, drawing_id=d.id, file_id=file_id or d.current_file_id, n=n, message="В очереди",
        requested_by=me.sub if me else ""))
    return build_id


async def emit_build(session: AsyncSession, kind: str, b, building_id: UUID, **data) -> dict:
    return await emit(session, f"import.build.{kind}", ("build", b.id),
                      {"build_id": str(b.id), "drawing_id": str(b.drawing_id), "n": b.n, **data},
                      building_id=building_id)
