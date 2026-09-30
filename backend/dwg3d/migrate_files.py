"""One-off import of file-based projects (data/jobs/<id>/job.json) into PostgreSQL.

  python -m dwg3d migrate-files [--dry-run] [--data DIR]

Projects already in the database are skipped, so the command can be re-run
(e.g. after a server still writing job.json was stopped: delete nothing, the
new ones are picked up). Files are not touched: job.json stays as a backup,
models and plans stay where they are and are referenced by path.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select

from . import db, store
from .models import Build, Floor, Job, Project

log = logging.getLogger("dwg3d.migrate")
VIEW_KEYS = ("furniture", "furniture_unplaced", "markers", "comments")


def _read(path: Path) -> dict | None:
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as ex:
        log.warning("%s: не читается (%s)", path, ex)
        return None
    if not isinstance(job, dict) or job.get("id") != path.parent.name or not job.get("input"):
        log.warning("%s: не похоже на job.json проекта", path)
        return None
    return job


def _rows(job: dict) -> tuple[Project, Build | None, Job]:
    pid = job["id"]
    view = job.get("view") or {}
    result = job.get("result")
    build_n = int(job.get("build") or 0) if result else 0
    if result and build_n < 1:
        build_n = 1
    p = Project(id=pid, name=view.get("name"), filename=job.get("filename") or job["input"],
                input_path=job["input"], size=int(job.get("size") or 0), config=job.get("config") or {},
                site=view.get("site"), detail=view.get("detail"),
                view={k: view[k] for k in VIEW_KEYS if k in view}, current_build=build_n,
                created_at=store.from_ts(job.get("created")), updated_at=store.from_ts(job.get("updated")))
    b = (Build(project_id=pid, n=build_n, result=result, config=job.get("config") or {}, out_dir="out",
               created_at=store.from_ts(job.get("updated"))) if result else None)
    status, error = job.get("status"), job.get("error")
    if status not in ("done", "error"):          # interrupted by a restart of the file-based server
        status, error = "error", "Сборка была прервана (перенос в базу данных)"
    j = Job(project_id=pid, status=status, stage=status, progress=1.0 if status == "done" else float(job.get("progress") or 0),
            message="Готово" if status == "done" else (job.get("message") or ""), error=error, trace=job.get("trace"),
            created_at=store.from_ts(job.get("created")), finished_at=store.from_ts(job.get("updated")))
    return p, b, j


def migrate(data: Path | None = None, dry_run: bool = False) -> dict:
    jobs_dir = Path(data) / "jobs" if data else store.data_dir()
    found = sorted(jobs_dir.glob("*/job.json"))
    with db.session() as s:
        existing = set(s.scalars(select(Project.id)))
    stats = {"found": len(found), "imported": 0, "skipped": 0, "unreadable": 0,
             "builds": 0, "floors": 0, "furniture": 0, "pins": 0}
    for path in found:
        job = _read(path)
        if job is None:
            stats["unreadable"] += 1
            continue
        if job["id"] in existing:
            stats["skipped"] += 1
            continue
        p, b, j = _rows(job)
        nf = len([f for f in (b.result.get("floors") or []) if f.get("bbox")]) if b else 0
        nfurn = len(p.view.get("furniture") or []) + len(p.view.get("furniture_unplaced") or [])
        npins = len(p.view.get("markers") or []) + len(p.view.get("comments") or [])
        print(f"  {p.id}  {p.filename[:40]:<40} сборка {p.current_build or '-':>2}  этажей {nf:>2}  "
              f"оборудование {nfurn:>3}  метки {npins:>3}  {j.status}")
        stats.update(imported=stats["imported"] + 1, builds=stats["builds"] + (1 if b else 0),
                     floors=stats["floors"] + nf, furniture=stats["furniture"] + nfurn, pins=stats["pins"] + npins)
        if dry_run:
            continue
        with db.session() as s:
            s.add(p)
            s.flush()
            if b is not None:
                s.add(b)
                s.flush()
                store.sync_floors(s, p.id, b.result)
            s.add(j)
    return stats


def verify(data: Path | None = None) -> list[str]:
    """Compare the database with the files: every readable job.json has its
    project with the same build, floors, furniture and pins."""
    jobs_dir = Path(data) / "jobs" if data else store.data_dir()
    problems = []
    with db.session() as s:
        for path in sorted(jobs_dir.glob("*/job.json")):
            job = _read(path)
            if job is None:
                continue
            p = store.get_project(s, job["id"])
            if p is None:
                problems.append(f"{job['id']}: нет в базе")
                continue
            want, _, _ = _rows(job)
            if p.current_build != want.current_build:
                problems.append(f"{p.id}: сборка {p.current_build}, в файле {want.current_build}")
            b = store.current_build(s, p)
            nf = len([f for f in ((b.result if b else {}).get("floors") or []) if f.get("bbox")])
            rows = s.scalar(select(func.count()).select_from(Floor)
                            .where(Floor.project_id == p.id, Floor.candidate.is_not(None)))
            if rows != nf:
                problems.append(f"{p.id}: этажей в базе {rows}, в сборке {nf}")
            view = store.view_of(p)
            for k in VIEW_KEYS:
                if len(view.get(k) or []) != len((job.get("view") or {}).get(k) or []):
                    problems.append(f"{p.id}: {k} — в базе {len(view.get(k) or [])}, "
                                    f"в файле {len((job.get('view') or {}).get(k) or [])}")
            if not (path.parent / p.input_path).is_file():
                problems.append(f"{p.id}: нет исходного файла {p.input_path}")
            if p.current_build and not (path.parent / "out" / "model.glb").is_file():
                problems.append(f"{p.id}: нет out/model.glb")
    return problems
