"""Backups: a PostgreSQL dump and a mirror of the file store.

  python -m dwg3d backup /backups [--keep 14]

  /backups/db/dwg3d-YYYYmmdd-HHMMSS.dump   pg_dump -Fc (restore: pg_restore -c -d ...);
                                           the newest `keep` dumps are kept
  /backups/files/<key>                     the file store (S3 or the data directory)
                                           mirrored: new and changed files copied,
                                           removed ones deleted

The `backup` service of docker-compose.yml runs it once a day.
"""
from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from . import db, files

log = logging.getLogger("dwg3d.backup")


def dump_db(dst_dir: Path, keep: int) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    url = db.database_url().replace("postgresql+psycopg://", "postgresql://")
    out = dst_dir / f"dwg3d-{datetime.now():%Y%m%d-%H%M%S}.dump"
    part = out.with_suffix(".dump.part")
    subprocess.run(["pg_dump", "-Fc", "--no-owner", "-f", str(part), "--dbname", url], check=True)
    part.replace(out)
    dumps = sorted(dst_dir.glob("dwg3d-*.dump"))
    for old in dumps[:-keep] if keep > 0 else []:
        old.unlink()
    return out


def mirror_files(dst_dir: Path) -> dict:
    st = files.store()
    dst_dir.mkdir(parents=True, exist_ok=True)
    have = {p.relative_to(dst_dir).as_posix(): p for p in dst_dir.rglob("*") if p.is_file()}
    keys = st.list("")
    res = {"copied": 0, "removed": 0, "total": len(keys)}
    for key, size in keys.items():
        p = have.get(key)
        if p is None or p.stat().st_size != size:
            st.download(key, dst_dir / key)
            res["copied"] += 1
    for rel, p in have.items():
        if rel not in keys:
            p.unlink()
            res["removed"] += 1
    return res


def run(dst: Path, keep: int = 14) -> dict:
    dump = dump_db(dst / "db", keep)
    res = mirror_files(dst / "files")
    return {"dump": str(dump), **res}
