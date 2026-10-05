"""The source drawing with the corrections of the 2D editor drawn in (DXF or DWG)."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

from twin_chassis import Problem

from . import storage
from .dwg.dxf_writer import dxf_to_dwg, export_edited_dxf, has_edits

log = logging.getLogger("twin.import.export")


def edited_drawing(d, f, b, fmt: str) -> tuple[str, str]:
    """Make (or find, made earlier) the file; returns its key in the bucket and the name to save it under.
    Blocking: call in a worker thread."""
    config = d.config or {}
    if not has_edits(config):
        raise Problem(409, "nothing_to_export", "В чертеже нет правок 2D-редактора — сохранять нечего")
    bucket = storage.bucket()
    stem = Path(f.filename).stem
    # the converted DXF of a DWG is among the files of its build
    source_key = f.storage_key if f.filename.lower().endswith(".dxf") else f"{b.out_prefix}/{stem}.dxf"
    digest = hashlib.sha1(json.dumps([source_key, config], sort_keys=True, ensure_ascii=False, default=str).encode())
    prefix = f"exports/{d.id}/{digest.hexdigest()[:12]}"
    name = f"{stem}_правки.{fmt}"
    if bucket.size(f"{prefix}/edited.{fmt}") is not None:
        return f"{prefix}/edited.{fmt}", name
    if fmt == "dwg" and (error := bucket.get_bytes(f"{prefix}/edited.dwg.error")) is not None:
        raise Problem(502, "conversion_failed", error.decode("utf-8"))     # a slow converter that already failed
    work = storage.workdir(d.id) / "export" / digest.hexdigest()[:12]
    work.mkdir(parents=True, exist_ok=True)
    try:
        dxf = work / "edited.dxf"
        if not dxf.exists() and not bucket.download(f"{prefix}/edited.dxf", dxf):
            source = work / "source.dxf"
            if not bucket.download(source_key, source):
                raise Problem(409, "not_ready", "Исходный чертёж в формате DXF не найден — пересоберите чертёж")
            export_edited_dxf(source, dxf, config, None)
            bucket.put_file(f"{prefix}/edited.dxf", dxf, storage.MEDIA[".dxf"])
        if fmt == "dwg":
            dwg = work / "edited.dwg"
            try:
                dxf_to_dwg(dxf, dwg)
            except Exception as ex:
                log.exception("DWG export failed")
                message = f"Не удалось записать DWG: {ex}. Скачайте DXF."
                bucket.put_bytes(f"{prefix}/edited.dwg.error", message.encode("utf-8"), "text/plain")
                raise Problem(502, "conversion_failed", message) from ex
            bucket.put_file(f"{prefix}/edited.dwg", dwg, storage.MEDIA[".dwg"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return f"{prefix}/edited.{fmt}", name
