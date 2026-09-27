"""End-to-end pipeline: DWG/DXF -> analysis -> 2D plans -> GLB + metadata."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

from .config import load_config
from .convert import ensure_dxf
from .extract import read_drawing
from .floors import align_floors, apply_manual, detect_candidates, resolve_stack
from .geometry import build_plan, plan_to_json
from .model3d import SceneBuilder

log = logging.getLogger(__name__)
Progress = Callable[[str, float, str], None]


def _noop(stage: str, frac: float, msg: str = ""):
    log.info("[%3d%%] %s %s", int(frac * 100), stage, msg)


def analyze(src: Path, work_dir: Path, cfg: dict, progress: Progress = _noop):
    """Convert + read + detect floors. Returns (drawing, candidates, info)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    progress("convert", 0.02, "DWG → DXF")
    dxf, method = ensure_dxf(src, work_dir)
    progress("read", 0.12, "Чтение DXF")
    d = read_drawing(dxf, cfg)
    progress("analyze", 0.30, "Поиск этажей")
    cands = detect_candidates(d, cfg)
    apply_manual(cands, cfg)
    info = {
        "source": Path(src).name, "dxf": dxf.name, "converter": method, **d.summary(),
        "layers": d.layer_stats,
    }
    return d, cands, info


def candidate_preview(d, c, max_segments=2500) -> dict:
    """Light SVG preview (walls/columns) of a floor candidate, y flipped."""
    x0, y0, x1, y1 = c.bbox
    parts, n = [], 0
    for s in d.shapes:
        if s.role not in ("walls", "columns") or not c.contains(s):
            continue
        p = s.pts
        parts.append("M" + "L".join(f"{x - x0:.2f} {y1 - y:.2f}" for x, y in p[:: max(1, len(p) // 12)]))
        n += 1
        if n >= max_segments:
            break
    return {"w": round(x1 - x0, 2), "h": round(y1 - y0, 2), "d": "".join(parts)}


def run(src: Path | str, out_dir: Path | str, config: dict | str | None = None,
        progress: Progress = _noop, debug_png: bool = True) -> dict:
    t0 = time.time()
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(config)
    d, cands, info = analyze(src, out_dir, cfg, progress)
    warnings = []
    if info["units_source"] == "heuristic":
        warnings.append(f"Единицы не указаны в файле, определены эвристически: {info['units']}")
    floors = resolve_stack(cands, cfg)
    if not floors:
        raise RuntimeError("Не найдено ни одного этажа: проверьте маппинг слоёв стен (layers.walls)")
    align_floors(d, floors, cfg)
    levels = [f.level for f in floors]
    if len(set(levels)) != len(levels):
        warnings.append("Несколько листов имеют одинаковый номер этажа — проверьте назначение этажей")

    plans = []
    for i, f in enumerate(floors):
        progress("geometry", 0.35 + 0.45 * i / len(floors), f"Геометрия: {f.name}")
        # small margin: cladding / insulation lies just outside the wall outline
        shapes = [s for s in d.shapes if f.contains(s, margin=1.0)]
        texts = [t for t in d.texts if f.contains(t)]
        inserts = [x for x in d.inserts if f.contains(x, margin=1.0)]
        edits = (cfg.get("edits") or {}).get(f.id) or {}
        plan = build_plan(shapes, texts, inserts, cfg, offset=f.offset, edits=edits)
        if plan.walls.is_empty:
            warnings.append(f"{f.name}: стены не найдены")
        plans.append(plan)

    progress("mesh", 0.82, "Построение 3D")
    ref = next((p for f, p in zip(floors, plans) if f.alignment == "reference"), plans[0])
    minx, miny, maxx, maxy = (ref.footprint if not ref.footprint.is_empty else ref.walls).bounds
    center = ((minx + maxx) / 2, (miny + maxy) / 2)
    sb = SceneBuilder(cfg, center)
    roots, floors_meta = [], []
    for f, plan in zip(floors, plans):
        extras = {"id": f.id, "name": f.name, "level": f.level, "elevation": f.elevation, "height": f.height}
        node, rooms = sb.floor(f.id, plan, f.elevation, f.height, extras)
        roots.append(node)
        floors_meta.append({**f.to_dict(), "node": f"floor_{f.id}", "rooms": rooms, "stats": plan.stats,
                            "plan": f"plans/floor_{f.id}.json"})
    roof_node = None
    if cfg["building"].get("roof", True) and floors:
        top_f, top_p = floors[-1], plans[-1]
        n = sb.roof(top_p.footprint, top_f.elevation + top_f.height)
        if n is not None:
            roots.append(n)
            roof_node = "roof"

    progress("export", 0.9, "Экспорт glTF")
    glb = out_dir / "model.glb"
    sb.save(glb, roots, {"generator": "dwg3d"})
    plans_dir = out_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    for f, plan in zip(floors, plans):
        (plans_dir / f"floor_{f.id}.json").write_text(json.dumps(plan_to_json(plan)), encoding="utf-8")
    exports = {"glb": glb.name}
    exp_cfg = cfg.get("export") or {}
    if exp_cfg.get("obj", True):
        progress("export", 0.93, "Экспорт OBJ")
        try:
            from .exports import export_obj_zip
            export_obj_zip(out_dir / "model_obj.zip", sb.meshes)
            exports["obj"] = "model_obj.zip"
        except Exception as ex:
            log.exception("OBJ export failed")
            warnings.append(f"OBJ не экспортирован: {ex}")
    if exp_cfg.get("ifc", True):
        progress("export", 0.96, "Экспорт IFC")
        try:
            from .exports import export_ifc
            export_ifc(out_dir / "model.ifc", floors, plans, cfg, center, Path(src).stem)
            exports["ifc"] = "model.ifc"
        except Exception as ex:
            log.exception("IFC export failed")
            warnings.append(f"IFC не экспортирован: {ex}")

    if debug_png:
        from .debug_plot import plot_overlay, plot_plan
        dbg = out_dir / "debug"
        dbg.mkdir(exist_ok=True)
        for f, plan in zip(floors, plans):
            plot_plan(plan, dbg / f"floor_{f.id}.png", f"{f.name}  (elev {f.elevation} m, h {f.height} m)")
        plot_overlay([(f.name, p) for f, p in zip(floors, plans)], dbg / "overlay.png")

    top = floors[-1].elevation + floors[-1].height
    from shapely.ops import unary_union
    allfp = unary_union([p.footprint for p in plans if not p.footprint.is_empty])
    bx0, by0, bx1, by1 = allfp.bounds if not allfp.is_empty else (0, 0, 0, 0)
    meta = {
        **{k: v for k, v in info.items() if k != "layers"},
        "model": glb.name,
        "center": [round(c, 4) for c in center],
        "floors": floors_meta,
        "roof_node": roof_node,
        "height_range": [floors[0].elevation - cfg["building"]["slab_thickness"], top],
        # glTF X range and Z range (plan Y is flipped) of the model
        "extent": {"x": [round(bx0 - center[0], 2), round(bx1 - center[0], 2)],
                   "z": [round(center[1] - by1, 2), round(center[1] - by0, 2)]},
        "candidates": [{**c.to_dict(), "preview": candidate_preview(d, c)} for c in cands],
        "exports": exports,
        "layers": info["layers"],
        "triangles": sb.tri_count,
        "warnings": warnings,
        "elapsed_s": round(time.time() - t0, 2),
        "config": cfg,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    progress("done", 1.0, "Готово")
    return meta
