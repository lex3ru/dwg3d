"""Where the files are: the service's bucket, and working copies for the pipeline.

  drawings/<drawing>/files/<file>/<name>  an uploaded DWG/DXF
  drawings/<drawing>/underlays/<name>     a picture a plan is drawn over (a drawn plan)
  builds/<build>/model.glb, plans/floor_<id>.json, model.ifc, model_obj.zip, <stem>.dxf
  exports/<drawing>/<key>/edited.dxf|dwg  the drawing with corrections drawn in

TWIN_DATA — the directory for working copies (default: a temporary one). The
pipeline keeps its caches there between builds of a drawing; losing it only
makes the next build slower.
"""
from __future__ import annotations

import os
import tempfile
from functools import cache
from pathlib import Path

from twin_chassis.files import Bucket

# what of a build's output directory is kept (caches and logs stay local)
KEEP = ("model.glb", "model.ifc", "model_obj.zip", "metadata.json")
MEDIA = {".glb": "model/gltf-binary", ".json": "application/json", ".ifc": "application/x-step",
         ".zip": "application/zip", ".dxf": "image/vnd.dxf", ".dwg": "application/acad"}


@cache
def bucket() -> Bucket:
    return Bucket("import")


@cache
def data_root() -> Path:
    root = Path(os.environ.get("TWIN_DATA") or Path(tempfile.gettempdir()) / "twin-import")
    root.mkdir(parents=True, exist_ok=True)
    return root


def workdir(drawing_id) -> Path:
    d = data_root() / "work" / str(drawing_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_key(drawing_id, file_id, filename: str) -> str:
    return f"drawings/{drawing_id}/files/{file_id}/{filename}"


def underlay_key(drawing_id, name: str) -> str:
    return f"drawings/{drawing_id}/underlays/{name}"


def build_prefix(build_id) -> str:
    return f"builds/{build_id}"


def push_build(out: Path, build_id, dxf_name: str | None) -> list[str]:
    """Upload the outputs of a build; returns the names stored."""
    b, prefix, names = bucket(), build_prefix(build_id), []
    wanted = [out / n for n in KEEP] + sorted((out / "plans").glob("floor_*.json"))
    if dxf_name:
        wanted.append(out / dxf_name)
    for path in wanted:
        if path.is_file():
            name = path.relative_to(out).as_posix()
            b.put_file(f"{prefix}/{name}", path, MEDIA.get(path.suffix.lower()))
            names.append(name)
    return names
