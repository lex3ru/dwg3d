"""The source drawing with the corrections of the 2D editor drawn in (DXF or DWG); a drawn plan as a drawing."""
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


def _sketch_file(d, work: Path, fmt: str) -> tuple[Path, dict]:
    """A drawn plan written as DXF (and converted to DWG when asked) in `work`; and where each floor lies on it."""
    from .sketch_dxf import sketch_dxf

    dxf = work / "plan.dxf"
    try:
        shifts = sketch_dxf(d.sketch, dxf)
    except RuntimeError as ex:
        raise Problem(409, "nothing_to_export", str(ex)) from ex
    if fmt == "dwg":
        try:
            dxf_to_dwg(dxf, work / "plan.dwg")
        except Exception as ex:
            log.exception("DWG export failed")
            raise Problem(502, "conversion_failed", f"Не удалось записать DWG: {ex}. Скачайте DXF.") from ex
    return work / f"plan.{fmt}", shifts


def sketch_drawing(d, fmt: str) -> tuple[Path, str]:
    """A drawn plan as DXF or DWG, as it is saved now: the file (in a work directory the caller removes) and the
    name to save it under. Blocking: call in a worker thread."""
    digest = hashlib.sha1(json.dumps(d.sketch, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    work = storage.workdir(d.id) / "export" / f"sketch-{digest}"
    work.mkdir(parents=True, exist_ok=True)
    path, _ = _sketch_file(d, work, fmt)
    return path, f"{d.name or 'План'}.{fmt}"


# ------------------------------------------------------- with objects ---
OBJECT_LAYER = "Объекты"
ATTRIBUTES = ("NAME", "INVENTORY_NO", "STATE", "RESPONSIBLE", "ROOM", "NOTE")


def _floors_of(src: Path, config: dict | None):
    """The floors of the source as the pipeline recognises them (their sheet and offset), and the drawing's scale."""
    from .dwg.config import load_config
    from .dwg.edits import resolve_items
    from .dwg.extract import read_doc, read_drawing
    from .dwg.floors import align_floors, apply_manual, detect_candidates, resolve_stack

    cfg = load_config(config)
    d = read_drawing(src, cfg, doc=read_doc(src))
    cands = detect_candidates(d, cfg)
    resolve_items(cfg, cands)
    apply_manual(cands, cfg)
    floors = resolve_stack(cands, cfg)
    align_floors(d, floors, cfg)
    return {f.id: f for f in floors}, d.scale


def _block(doc, kind: dict, scale: float) -> str:
    """A block per type: its footprint centred on the origin, the front edge marked, the attributes."""
    import re

    from ezdxf.enums import TextEntityAlignment

    name = "TWIN_" + re.sub(r"[^0-9A-Za-z_.-]", "_", kind["id"])
    if name in doc.blocks:
        return name
    blk = doc.blocks.new(name)
    w, d = max(kind["w"], 0.1) / scale, max(kind["d"], 0.1) / scale
    blk.add_lwpolyline([(-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)], close=True,
                       dxfattribs={"layer": "0"})
    blk.add_line((-w / 2, -d / 2 + d * 0.08), (w / 2, -d / 2 + d * 0.08), dxfattribs={"layer": "0"})
    h = max(min(w, d) * 0.12, 0.05 / scale)
    for n, tag in enumerate(ATTRIBUTES):
        a = blk.add_attdef(tag, insert=(0, -h * 1.5 * n), height=h, dxfattribs={"layer": "0"})
        a.set_placement((0, -h * 1.5 * n), align=TextEntityAlignment.MIDDLE_CENTER)
        a.is_invisible = tag != "NAME"
    return name


def drawing_with_objects(d, f, b, fmt: str, objects: list[dict], types: dict[str, dict]) -> tuple[Path, str, dict]:
    """The source drawing (with the editor's corrections, when there are any) and the objects drawn
    on their floors as blocks with attributes. objects: [{floor (candidate id), at [x, y] in plan metres,
    angle, type, name, inventory_no, state, responsible, room, note}]; types: {id: {id, w, d}}.
    Returns the file (in a work directory the caller removes), its name and what was drawn.
    Blocking: call in a worker thread."""
    import ezdxf

    if d.kind == "sketch":
        return _sketch_with_objects(d, fmt, objects, types)
    bucket = storage.bucket()
    stem = Path(f.filename).stem
    source_key = f.storage_key if f.filename.lower().endswith(".dxf") else f"{b.out_prefix}/{stem}.dxf"
    digest = hashlib.sha1(json.dumps(objects, sort_keys=True, default=str).encode()).hexdigest()[:12]
    work = storage.workdir(d.id) / "objects" / digest
    work.mkdir(parents=True, exist_ok=True)
    source = work / "source.dxf"
    if not bucket.download(source_key, source):
        shutil.rmtree(work, ignore_errors=True)
        raise Problem(409, "not_ready", "Исходный чертёж в формате DXF не найден — пересоберите чертёж")
    edited = work / "edited.dxf"
    export_edited_dxf(source, edited, d.config or {}, None)
    floors, scale = _floors_of(source, d.config or {})
    return _draw_objects(ezdxf.readfile(str(edited)), floors, scale, work, fmt, objects, types, stem)


def _sketch_with_objects(d, fmt: str, objects: list[dict], types: dict[str, dict]) -> tuple[Path, str, dict]:
    """A drawn plan with the objects: its floors are where sketch_dxf laid them, in meters."""
    from types import SimpleNamespace

    import ezdxf

    digest = hashlib.sha1(json.dumps([d.sketch, objects], sort_keys=True, default=str).encode()).hexdigest()[:12]
    work = storage.workdir(d.id) / "objects" / f"sketch-{digest}"
    work.mkdir(parents=True, exist_ok=True)
    source, shifts = _sketch_file(d, work, "dxf")
    # the objects are placed at (x − offset) / scale: a floor moved by (dx, dy) has the offset (−dx, −dy)
    floors = {fid: SimpleNamespace(space="Model", offset=(-dx, -dy)) for fid, (dx, dy) in shifts.items()}
    return _draw_objects(ezdxf.readfile(str(source)), floors, 1.0, work, fmt, objects, types, d.name or "План")


def _draw_objects(doc, floors: dict, scale: float, work: Path, fmt: str, objects: list[dict], types: dict[str, dict],
                  stem: str) -> tuple[Path, str, dict]:
    """The objects drawn into the document on their floors as blocks with attributes; the file written."""
    if OBJECT_LAYER not in doc.layers:
        doc.layers.add(OBJECT_LAYER, color=150)
    stats = {"drawn": 0, "skipped": 0}
    for o in objects:
        floor, kind = floors.get(o.get("floor")), types.get(o.get("type"))
        if floor is None or kind is None or not o.get("at"):
            stats["skipped"] += 1
            continue
        layout = doc.modelspace() if floor.space == "Model" else doc.layouts.get(floor.space)
        ox, oy = floor.offset
        x, y = o["at"]
        ref = layout.add_blockref(_block(doc, kind, scale), ((x - ox) / scale, (y - oy) / scale),
                                  dxfattribs={"layer": OBJECT_LAYER, "rotation": float(o.get("angle") or 0)})
        ref.add_auto_attribs({tag: str(o.get(tag.lower()) or "") for tag in ATTRIBUTES})
        stats["drawn"] += 1
    out = work / f"objects.{fmt}"
    if fmt == "dxf":
        doc.saveas(str(out))
    else:
        doc.saveas(str(work / "objects.dxf"))
        try:
            dxf_to_dwg(work / "objects.dxf", out)
        except Exception as ex:
            log.exception("DWG export failed")
            shutil.rmtree(work, ignore_errors=True)
            raise Problem(502, "conversion_failed", f"Не удалось записать DWG: {ex}. Скачайте DXF.") from ex
    return out, f"{stem}_объекты.{fmt}", stats
