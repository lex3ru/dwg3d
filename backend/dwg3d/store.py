"""Projects, builds, floors and the job queue in PostgreSQL.

Files stay on disk: <DWG3D_DATA>/jobs/<project id>/ holds the upload,
out/ (model, plans, exports, converted DXF) and detail.glb.

The API keeps its job-shaped JSON (`public()`), assembled from the project,
its latest job and its current build.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import viewdata
from .edits import _floor_ns, anchor_of, match
from .models import JOB_ACTIVE, Build, Floor, Job, Pin, Placement, Project

ROOT = Path(__file__).resolve().parents[2]
# viewer settings stored in project columns; furniture and pins are rows (viewdata.py)
VIEW_COLUMNS = ("name", "site", "detail")


def data_dir() -> Path:
    return Path(os.environ.get("DWG3D_DATA", ROOT / "data")) / "jobs"


def project_dir(pid: str) -> Path:
    return data_dir() / pid


def ts(d: datetime | None) -> float | None:
    return d.timestamp() if d else None


def from_ts(t) -> datetime:
    return datetime.fromtimestamp(float(t), tz=timezone.utc) if t else datetime.now(timezone.utc)


def get_project(s: Session, pid: str, lock: bool = False) -> Project | None:
    q = select(Project).where(Project.id == pid, Project.deleted_at.is_(None))
    return s.scalar(q.with_for_update() if lock else q)


def latest_job(s: Session, pid: str) -> Job | None:
    return s.scalar(select(Job).where(Job.project_id == pid).order_by(Job.id.desc()).limit(1))


def current_build(s: Session, p: Project) -> Build | None:
    return s.get(Build, (p.id, p.current_build)) if p.current_build else None


def view_of(s: Session, p: Project) -> dict:
    v = {k: getattr(p, k) for k in VIEW_COLUMNS if getattr(p, k) is not None}
    return {**v, **viewdata.view_data(s, p.id)}


def set_settings(p: Project, v: dict):
    """name / site / detail (validated), None removes."""
    for k in VIEW_COLUMNS:
        if k in v:
            setattr(p, k, v[k])
    p.updated_at = func.now()


def status_of(p: Project, job: Job | None) -> str:
    return job.status if job else ("done" if p.current_build else "error")


def public(s: Session, p: Project, job: Job | None = None, build: Build | None = None) -> dict:
    """The job-shaped JSON the viewer expects (no input path, no trace)."""
    job = job or latest_job(s, p.id)
    build = build or current_build(s, p)
    out = {"id": p.id, "filename": p.filename, "size": p.size, "status": status_of(p, job),
           "stage": job.stage if job else "done", "progress": job.progress if job else 1.0,
           "message": job.message if job else "", "error": job.error if job else None,
           "config": p.config or {}, "created": ts(p.created_at), "updated": ts(p.updated_at),
           "build": p.current_build}
    if build is not None:
        out["result"] = build.result
    view = view_of(s, p)
    if view:
        out["view"] = view
    if out["status"] == "done":
        out["model_url"] = f"/api/jobs/{p.id}/files/model.glb?v={p.current_build}"
        out["metadata_url"] = f"/api/jobs/{p.id}/files/metadata.json?v={p.current_build}"
    return out


def list_projects(s: Session) -> list[dict]:
    """Building switcher: newest first, without reading build results."""
    last = (select(Job.project_id, func.max(Job.id).label("jid")).group_by(Job.project_id).subquery())
    nfloors = func.coalesce(func.jsonb_array_length(Build.result["floors"]), 0)
    q = (select(Project.id, Project.name, Project.filename, Project.updated_at, Project.current_build,
                Job.status, nfloors)
         .outerjoin(last, last.c.project_id == Project.id)
         .outerjoin(Job, Job.id == last.c.jid)
         .outerjoin(Build, (Build.project_id == Project.id) & (Build.n == Project.current_build))
         .where(Project.deleted_at.is_(None))
         .order_by(Project.updated_at.desc()))
    return [{"id": pid, "filename": fn, "status": st or ("done" if cb else "error"), "updated": ts(up),
             "floors": nf, "name": name or Path(fn or "").stem}
            for pid, name, fn, up, cb, st, nf in s.execute(q)]


def enqueue(s: Session, p: Project) -> Job:
    """Queue a build; the caller holds the project row lock (see has_active)."""
    job = Job(project_id=p.id, status="queued", stage="queued", progress=0.0, message="В очереди")
    s.add(job)
    p.updated_at = func.now()
    s.flush()
    return job


def has_active(s: Session, pid: str) -> bool:
    return s.scalar(select(func.count()).select_from(Job)
                    .where(Job.project_id == pid, Job.status.in_(JOB_ACTIVE))) > 0


def sync_floors(s: Session, pid: str, result: dict, old: dict | None = None) -> list[str]:
    """Match the project's floors to the floors of a new build by their sheet
    anchor (like the edits, see edits.py), so a floor keeps its row while its
    candidate id (c0, c3...) changes between builds, and move its furniture
    and pins with it: by the change of the alignment offset and elevation, and
    pins (glTF coordinates) also by the change of the model centre `old` -> `result`.
    A floor whose sheet is not found keeps its row (candidate NULL) and its
    rows stay where they were until the sheet is back. Returns warnings."""
    rows = s.scalars(select(Floor).where(Floor.project_id == pid)
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
            r = Floor(project_id=pid)
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
    for fid, (dx, dy, dz) in moves.items():
        if dx or dy:
            s.execute(update(Placement).where(Placement.project_id == pid, Placement.floor_id == fid)
                      .values(x=Placement.x + dx, y=Placement.y + dy))
        if dx or dy or dz or cdx or cdz:
            s.execute(update(Pin).where(Pin.project_id == pid, Pin.floor_id == fid)
                      .values(x=Pin.x + (cdx + dx), y=Pin.y + dz, z=Pin.z + (cdz - dy)))
    if cdx or cdz:                        # building-wide pins and pins of lost floors
        s.execute(update(Pin).where(Pin.project_id == pid,
                                    Pin.floor_id.is_(None) | Pin.floor_id.not_in(list(moves) or [-1]))
                  .values(x=Pin.x + cdx, z=Pin.z + cdz))

    lost = s.execute(select(Floor.name, func.count()).join(Placement, Placement.floor_id == Floor.id)
                     .where(Floor.project_id == pid, Floor.candidate.is_(None)).group_by(Floor.name)).all()
    n = sum(c for _, c in lost)
    if not n:
        return []
    names = ", ".join(sorted(name or "?" for name, _ in lost))
    return [f"Оборудование ({n} шт.) не привязано: этаж «{names}» не найден в новой сборке. "
            f"Оно сохранено — перенесите его на этаж в панели «Мебель и оборудование»"]


def delete_stale(s: Session, days: float) -> list[str]:
    """Projects untouched for `days` without an active build: rows removed, ids returned."""
    cutoff = func.now() - func.make_interval(0, 0, 0, 0, 0, 0, days * 86400)
    active = select(Job.project_id).where(Job.status.in_(JOB_ACTIVE))
    return list(s.scalars(delete(Project).where(Project.updated_at < cutoff, Project.id.not_in(active))
                          .returning(Project.id)))


def fail_stale_jobs(s: Session, seconds: int) -> int:
    """Running jobs whose worker stopped sending heartbeats (process killed / restarted)."""
    return s.execute(update(Job).where(Job.status == "running",
                                       Job.heartbeat_at < func.now() - func.make_interval(0, 0, 0, 0, 0, 0, seconds))
                     .values(status="error", stage="error", finished_at=func.now(),
                             error="Сервер был перезапущен во время обработки")).rowcount
