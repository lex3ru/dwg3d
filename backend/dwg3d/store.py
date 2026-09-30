"""Projects, drawings, builds, floors and the job queue in PostgreSQL.

A project holds drawings; a drawing is one uploaded DWG/DXF with its builds.
Its files (the upload, out/ with the model, plans, exports and converted
DXF, detail.glb) are in the file store under drawings/<id>/ (files.py).

The API describes a drawing with job-shaped JSON (`public()`), assembled
from the drawing, its latest job and its current build.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import layers, viewdata
from .edits import _floor_ns, anchor_of, match
from .models import JOB_ACTIVE, Build, Drawing, Floor, Job, LayerObject, Pin, Project

# viewer settings stored in drawing columns; furniture and pins are rows (viewdata.py)
VIEW_COLUMNS = ("name", "site", "detail")


def ts(d: datetime | None) -> float | None:
    return d.timestamp() if d else None


def from_ts(t) -> datetime:
    return datetime.fromtimestamp(float(t), tz=timezone.utc) if t else datetime.now(timezone.utc)


def get_project(s: Session, pid: str, lock: bool = False) -> Project | None:
    q = select(Project).where(Project.id == pid, Project.deleted_at.is_(None))
    return s.scalar(q.with_for_update() if lock else q)


def get_drawing(s: Session, did: str, lock: bool = False) -> Drawing | None:
    q = (select(Drawing).join(Project, Project.id == Drawing.project_id)
         .where(Drawing.id == did, Drawing.deleted_at.is_(None), Project.deleted_at.is_(None)))
    return s.scalar(q.with_for_update(of=Drawing) if lock else q)


def drawing_name(d: Drawing) -> str:
    return d.name or Path(d.filename or "").stem


def touch_project(s: Session, pid: str):
    s.execute(update(Project).where(Project.id == pid).values(updated_at=func.now()))


def latest_job(s: Session, did: str) -> Job | None:
    return s.scalar(select(Job).where(Job.drawing_id == did).order_by(Job.id.desc()).limit(1))


def current_build(s: Session, d: Drawing) -> Build | None:
    return s.get(Build, (d.id, d.current_build)) if d.current_build else None


def view_of(s: Session, d: Drawing) -> dict:
    v = {k: getattr(d, k) for k in VIEW_COLUMNS if getattr(d, k) is not None}
    return {**v, **viewdata.view_data(s, d.id)}


def set_settings(d: Drawing, v: dict):
    """name / site / detail (validated), None removes."""
    for k in VIEW_COLUMNS:
        if k in v:
            setattr(d, k, v[k])
    d.updated_at = func.now()


def status_of(d: Drawing, job: Job | None) -> str:
    return job.status if job else ("done" if d.current_build else "error")


def public(s: Session, d: Drawing, job: Job | None = None, build: Build | None = None) -> dict:
    """The job-shaped JSON the viewer expects (no input path, no trace)."""
    job = job or latest_job(s, d.id)
    build = build or current_build(s, d)
    out = {"id": d.id, "project_id": d.project_id, "name": drawing_name(d), "filename": d.filename,
           "size": d.size, "status": status_of(d, job),
           "stage": job.stage if job else "done", "progress": job.progress if job else 1.0,
           "message": job.message if job else "", "error": job.error if job else None,
           "config": d.config or {}, "created": ts(d.created_at), "updated": ts(d.updated_at),
           "build": d.current_build}
    if build is not None:
        out["result"] = build.result
    view = view_of(s, d)
    if view:
        out["view"] = view
    out["layers"] = layers.list_layers(s, d.project_id)
    if out["status"] == "done":
        out["model_url"] = f"/api/drawings/{d.id}/files/model.glb?v={d.current_build}"
        out["metadata_url"] = f"/api/drawings/{d.id}/files/metadata.json?v={d.current_build}"
    return out


def list_drawings(s: Session, project_id: str | None = None) -> list[dict]:
    """Drawings (of one project, or all): newest first, without reading build results."""
    last = (select(Job.drawing_id, func.max(Job.id).label("jid")).group_by(Job.drawing_id).subquery())
    nfloors = func.coalesce(func.jsonb_array_length(Build.result["floors"]), 0)
    q = (select(Drawing.id, Drawing.project_id, Drawing.name, Drawing.filename, Drawing.size, Drawing.updated_at,
                Drawing.current_build, Job.status, Job.progress, nfloors)
         .join(Project, Project.id == Drawing.project_id)
         .outerjoin(last, last.c.drawing_id == Drawing.id)
         .outerjoin(Job, Job.id == last.c.jid)
         .outerjoin(Build, (Build.drawing_id == Drawing.id) & (Build.n == Drawing.current_build))
         .where(Drawing.deleted_at.is_(None), Project.deleted_at.is_(None))
         .order_by(Drawing.updated_at.desc()))
    if project_id is not None:
        q = q.where(Drawing.project_id == project_id)
    return [{"id": did, "project_id": pid, "filename": fn, "size": size,
             "status": st or ("done" if cb else "error"), "progress": pr if st else 1.0,
             "updated": ts(up), "floors": nf, "build": cb, "name": name or Path(fn or "").stem}
            for did, pid, name, fn, size, up, cb, st, pr, nf in s.execute(q)]


def project_json(s: Session, p: Project, drawings: list[dict] | None = None) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "created": ts(p.created_at),
            "updated": ts(p.updated_at),
            "drawings": drawings if drawings is not None else list_drawings(s, p.id)}


def list_projects(s: Session) -> list[dict]:
    """Projects with their drawings, most recently changed first."""
    drawings: dict[str, list[dict]] = {}
    for d in list_drawings(s):
        drawings.setdefault(d["project_id"], []).append(d)
    q = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.updated_at.desc())
    return [project_json(s, p, drawings.get(p.id, [])) for p in s.scalars(q)]


def enqueue(s: Session, d: Drawing) -> Job:
    """Queue a build; the caller holds the drawing row lock (see has_active)."""
    job = Job(drawing_id=d.id, status="queued", stage="queued", progress=0.0, message="В очереди")
    s.add(job)
    d.updated_at = func.now()
    touch_project(s, d.project_id)
    s.flush()
    return job


def has_active(s: Session, did: str) -> bool:
    return s.scalar(select(func.count()).select_from(Job)
                    .where(Job.drawing_id == did, Job.status.in_(JOB_ACTIVE))) > 0


def sync_floors(s: Session, did: str, result: dict, old: dict | None = None,
                moves_out: dict | None = None) -> list[str]:
    """Match the drawing's floors to the floors of a new build by their sheet
    anchor (like the edits, see edits.py), so a floor keeps its row while its
    candidate id (c0, c3...) changes between builds, and move its layer
    objects and pins with it: by the change of the alignment offset and
    elevation, and pins (glTF coordinates) also by the change of the model
    centre `old` -> `result`. A floor whose sheet is not found keeps its row
    (candidate NULL) and its rows stay where they were until the sheet is
    back. Returns warnings; the moves (floor row id -> dx, dy, dz) go to
    `moves_out` (for the rooms, see rooms.sync)."""
    rows = s.scalars(select(Floor).where(Floor.drawing_id == did)
                     .order_by(Floor.candidate.is_(None), Floor.id)).all()
    new = [f for f in result.get("floors") or [] if f.get("bbox")]
    ns = [_floor_ns(f) for f in new]
    taken: dict[str, Floor] = {}
    for r in rows:
        f = match(r.anchor, [x for x in ns if x.id not in taken], prefer_id=r.candidate)
        if f is not None:
            taken[f.id] = r
    moves: dict[int, tuple[float, float, float]] = {}
    for f in new:
        r = taken.get(f["id"])
        if r is not None:
            ox, oy = r.anchor.get("offset") or (0.0, 0.0)
            nx, ny = f.get("offset") or (0.0, 0.0)
            moves[r.id] = (nx - ox, ny - oy, float(f.get("elevation") or 0.0) - float(r.elevation or 0.0))
    for r in rows:                       # candidates may swap: clear first (unique per project)
        r.candidate = None
    s.flush()
    for f in new:
        r = taken.get(f["id"])
        if r is None:
            r = Floor(drawing_id=did)
            s.add(r)
        r.anchor = anchor_of(f)
        r.candidate = f["id"]
        r.name = f.get("name")
        r.level = f.get("level")
        r.elevation = f.get("elevation")
        r.height = f.get("height")
    s.flush()

    # plan -> glTF: x = px - cx, z = -(py - cy)
    ocx, ocy = ((old or {}).get("center") or (0.0, 0.0)) if old else (result.get("center") or (0.0, 0.0))
    ncx, ncy = result.get("center") or (0.0, 0.0)
    cdx, cdz = ocx - ncx, ncy - ocy
    if moves_out is not None:
        moves_out.update(moves)
    for fid, (dx, dy, dz) in moves.items():
        if dx or dy:
            s.execute(update(LayerObject).where(LayerObject.drawing_id == did, LayerObject.floor_id == fid)
                      .values(x=LayerObject.x + dx, y=LayerObject.y + dy))
            for o in s.scalars(select(LayerObject).where(LayerObject.drawing_id == did, LayerObject.floor_id == fid,
                                                         LayerObject.points.is_not(None))):
                o.points = [[px + dx, py + dy] for px, py in o.points]
        if dx or dy or dz or cdx or cdz:
            s.execute(update(Pin).where(Pin.drawing_id == did, Pin.floor_id == fid)
                      .values(x=Pin.x + (cdx + dx), y=Pin.y + dz, z=Pin.z + (cdz - dy)))
    if cdx or cdz:                        # building-wide pins and pins of lost floors
        s.execute(update(Pin).where(Pin.drawing_id == did,
                                    Pin.floor_id.is_(None) | Pin.floor_id.not_in(list(moves) or [-1]))
                  .values(x=Pin.x + cdx, z=Pin.z + cdz))

    lost = s.execute(select(Floor.name, func.count()).join(LayerObject, LayerObject.floor_id == Floor.id)
                     .where(Floor.drawing_id == did, Floor.candidate.is_(None)).group_by(Floor.name)).all()
    n = sum(c for _, c in lost)
    if not n:
        return []
    names = ", ".join(sorted(name or "?" for name, _ in lost))
    return [f"Объекты слоёв ({n} шт.) не привязаны: этаж «{names}» не найден в новой сборке. "
            f"Они сохранены — перенесите их на этаж в панели слоя"]


def delete_stale(s: Session, days: float) -> list[str]:
    """Projects untouched for `days` without an active build: rows removed,
    the ids of their drawings (file directories) returned."""
    cutoff = func.now() - func.make_interval(0, 0, 0, 0, 0, 0, days * 86400)
    active = select(Drawing.project_id).join(Job, Job.drawing_id == Drawing.id).where(Job.status.in_(JOB_ACTIVE))
    gone = list(s.scalars(select(Project.id).where(Project.updated_at < cutoff, Project.id.not_in(active))))
    if not gone:
        return []
    dirs = list(s.scalars(select(Drawing.id).where(Drawing.project_id.in_(gone))))
    s.execute(delete(Project).where(Project.id.in_(gone)))
    return dirs


def fail_stale_jobs(s: Session, seconds: int) -> int:
    """Running jobs whose worker stopped sending heartbeats (process killed / restarted)."""
    return s.execute(update(Job).where(Job.status == "running",
                                       Job.heartbeat_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, seconds))
                     .values(status="error", stage="error", finished_at=func.now(),
                             error="Сервер был перезапущен во время обработки")).rowcount
