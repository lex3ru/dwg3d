"""End-to-end pipeline: DWG/DXF -> analysis -> 2D plans -> GLB + metadata.

Rebuilds are incremental: the parsed drawing and each floor's 2D plan are
cached (pickles in `<out>/cache/`, keyed by the source file, the config
sections they depend on and the package source code), so an edit in the 2D
editor recomputes only the edited floor. Debug PNGs are rendered on demand
from the cached plans (`render_debug`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Callable

from .config import load_config
from .convert import ensure_dxf
from .edits import resolve_edits, resolve_items
from .extract import read_drawing
from .floors import align_floors, apply_manual, detect_candidates, resolve_stack
from .geometry import build_plan, plan_to_json
from .model3d import SceneBuilder
from .semantics import classify_room, find_entrances, floor_pois, legend, room_type_rules

log = logging.getLogger(__name__)
Progress = Callable[[str, float, str], None]


def _noop(stage: str, frac: float, msg: str = ""):
    log.info("[%3d%%] %s %s", int(frac * 100), stage, msg)


# ----------------------------------------------------------------- cache ---
def _code_version() -> str:
    """Hash of the package sources: a changed heuristic invalidates caches."""
    h = hashlib.sha1()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.read_bytes())
    h.update(Path(__file__).with_name("default_config.yaml").read_bytes())
    return h.hexdigest()[:12]


CODE_VERSION = _code_version()


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps([CODE_VERSION, *parts], sort_keys=True, ensure_ascii=False,
                                   default=str).encode()).hexdigest()[:16]


def _load(p: Path):
    try:
        return pickle.loads(p.read_bytes())
    except Exception:          # missing / truncated / from an incompatible version
        return None


def _store(p: Path, obj):
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(p)
    except Exception:
        log.exception("cache write failed: %s", p)


def _prune(cache: Path, pattern: str, keep: set[str]):
    for p in cache.glob(pattern):
        if p.name not in keep:
            p.unlink(missing_ok=True)


def _drawing_key(dxf: Path, cfg: dict) -> str:
    st = dxf.stat()
    return _key("drawing", dxf.name, st.st_size, st.st_mtime_ns, cfg.get("units"), cfg.get("layers"),
                cfg.get("blocks"), cfg["geometry"].get("arc_tolerance"), cfg["floors"].get("mode"))


# -------------------------------------------------------------- analysis ---
def analyze(src: Path, work_dir: Path, cfg: dict, progress: Progress = _noop, cache: Path | None = None):
    """Convert + read + detect floors. Returns (drawing, candidates, info)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    progress("convert", 0.02, "DWG → DXF")
    dxf, method = ensure_dxf(src, work_dir)
    progress("read", 0.12, "Чтение DXF")
    d = None
    if cache is not None:
        key = _drawing_key(dxf, cfg)
        name = f"drawing_{key}.pkl"
        d = _load(cache / name)
        if d is None:
            d = read_drawing(dxf, cfg)
            _store(cache / name, d)
        else:
            progress("read", 0.25, "Чтение DXF (кэш)")
        _prune(cache, "drawing_*.pkl", {name})
        d.cache_key = key
    else:
        d = read_drawing(dxf, cfg)
    progress("analyze", 0.30, "Поиск этажей")
    cands = detect_candidates(d, cfg)
    item_warnings = resolve_items(cfg, cands)
    apply_manual(cands, cfg)
    info = {
        "source": Path(src).name, "dxf": dxf.name, "converter": method, **d.summary(),
        "layers": d.layer_stats, "item_warnings": item_warnings,
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


def floor_plan(d, f, cfg, edits: dict, cache: Path | None = None):
    """2D plan of one floor, from the cache when nothing it depends on changed."""
    name = None
    if cache is not None and getattr(d, "cache_key", None):
        plan_cfg = {k: v for k, v in cfg.items() if k not in ("edits", "edits_unmatched", "export", "floors")}
        key = _key("plan", d.cache_key, plan_cfg, f.space, f.owner, f.bbox, f.offset, edits)
        name = f"plan_{f.id}_{key}.pkl"
        plan = _load(cache / name)
        if plan is not None:
            return plan, name, True
    shapes = [s for s in d.shapes if f.contains(s, margin=1.0)]    # cladding lies just outside
    texts = [t for t in d.texts if f.contains(t)]
    inserts = [x for x in d.inserts if f.contains(x, margin=1.0)]
    plan = build_plan(shapes, texts, inserts, cfg, offset=f.offset, edits=edits)
    if name:
        _store(cache / name, plan)
    return plan, name, False


# ---------------------------------------------------------- plausibility ---
def check_quality(floors, plans, triangles: int) -> dict:
    """Flags results that are technically "done" but most likely wrong
    (wrong layer mapping, wrong units, a sheet that is not a plan...)."""
    issues = []
    for f, p in zip(floors, plans):
        st = p.stats
        fp, wa = st.get("footprint_m2", 0), st.get("wall_area_m2", 0)
        if wa < 1.0:
            issues.append(f"{f.name}: стен почти нет ({wa} м²) — проверьте роли слоёв")
        elif fp < 10 or fp > 200_000:
            issues.append(f"{f.name}: площадь этажа {fp} м² — возможно, неверные единицы или слои")
        elif wa / fp > 0.5:
            issues.append(f"{f.name}: стены занимают {round(100 * wa / fp)}% площади — "
                          "вероятно, на слой стен попали штриховки или заливки")
        elif fp > 30 and st.get("rooms", 0) == 0:
            issues.append(f"{f.name}: не найдено ни одного помещения")
    if triangles < 500:
        issues.append(f"Модель почти пустая ({triangles} треугольников)")
    fps = sorted(p.stats.get("footprint_m2", 0) for p in plans)
    if len(fps) >= 3 and fps[len(fps) // 2] > 0:
        med = fps[len(fps) // 2]
        for f, p in zip(floors, plans):
            a = p.stats.get("footprint_m2", 0)
            if a > 4 * med or 0 < a < med / 4:
                issues.append(f"{f.name}: площадь {a} м² сильно отличается от типичной ({med} м²) — "
                              "проверьте разбиение на этажи")
    return {"status": "suspect" if issues else "ok", "issues": issues}


# ------------------------------------------------------------ debug PNGs ---
def _write_debug_index(cache: Path, floors, plan_files):
    idx = [{"id": f.id, "title": f"{f.name}  (elev {f.elevation} m, h {f.height} m)", "name": f.name, "plan": pf}
           for f, pf in zip(floors, plan_files)]
    (cache / "debug_index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")


def render_debug(out_dir: Path, name: str) -> Path | None:
    """Render `debug/<name>` (floor_<id>.png or overlay.png) from cached plans."""
    from .debug_plot import plot_overlay, plot_plan

    out_dir = Path(out_dir)
    cache = out_dir / "cache"
    try:
        idx = json.loads((cache / "debug_index.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    dst = out_dir / "debug" / name
    dst.parent.mkdir(exist_ok=True)
    if name == "overlay.png":
        plans = [(e["name"], _load(cache / e["plan"])) for e in idx if e.get("plan")]
        if not plans or any(p is None for _, p in plans):
            return None
        plot_overlay(plans, dst)
        return dst
    e = next((e for e in idx if f"floor_{e['id']}.png" == name), None)
    plan = _load(cache / e["plan"]) if e and e.get("plan") else None
    if plan is None:
        return None
    plot_plan(plan, dst, e["title"])
    return dst


# ------------------------------------------------------------------- run ---
def run(src: Path | str, out_dir: Path | str, config: dict | str | None = None,
        progress: Progress = _noop, debug_png: bool = True, use_cache: bool = True) -> dict:
    t0 = time.time()
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "cache" if use_cache else None
    if cache:
        cache.mkdir(exist_ok=True)
    cfg = load_config(config)
    d, cands, info = analyze(src, out_dir, cfg, progress, cache)
    warnings = list(info.pop("item_warnings"))
    if info["units_source"] == "heuristic":
        warnings.append(f"Единицы не указаны в файле, определены эвристически: {info['units']}")
    floors = resolve_stack(cands, cfg)
    if not floors:
        raise RuntimeError("Не найдено ни одного этажа: проверьте маппинг слоёв стен (layers.walls)")
    align_floors(d, floors, cfg)
    levels = [f.level for f in floors]
    if len(set(levels)) != len(levels):
        warnings.append("Несколько листов имеют одинаковый номер этажа — проверьте назначение этажей")
    applied, stored, unmatched, edit_warnings = resolve_edits(cfg, floors)
    warnings += edit_warnings

    plans, plan_files, n_cached = [], [], 0
    for i, f in enumerate(floors):
        progress("geometry", 0.35 + 0.45 * i / len(floors), f"Геометрия: {f.name}")
        plan, pf, hit = floor_plan(d, f, cfg, applied.get(f.id) or {}, cache)
        n_cached += hit
        if plan.walls.is_empty:
            warnings.append(f"{f.name}: стены не найдены")
        plans.append(plan)
        plan_files.append(pf)
    if cache:
        _prune(cache, "plan_*.pkl", {pf for pf in plan_files if pf})
        _write_debug_index(cache, floors, plan_files)

    progress("mesh", 0.82, "Построение 3D")
    ref = next((p for f, p in zip(floors, plans) if f.alignment == "reference"), plans[0])
    minx, miny, maxx, maxy = (ref.footprint if not ref.footprint.is_empty else ref.walls).bounds
    center = ((minx + maxx) / 2, (miny + maxy) / 2)
    sb = SceneBuilder(cfg, center)
    roots, floors_meta, pois = [], [], []
    rules = room_type_rules(cfg)
    for f, plan in zip(floors, plans):
        extras = {"id": f.id, "name": f.name, "level": f.level, "elevation": f.elevation, "height": f.height}
        types = [classify_room(r, plan, rules) for r in plan.rooms]
        node, rooms = sb.floor(f.id, plan, f.elevation, f.height, extras, types)
        roots.append(node)
        floors_meta.append({**f.to_dict(), "node": f"floor_{f.id}", "rooms": rooms, "stats": plan.stats,
                            "plan": f"plans/floor_{f.id}.json"})
        pois += floor_pois(f, plan, types, center)
    entrances = find_entrances(floors, plans, cfg, center)
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
    for p in plans_dir.glob("floor_*.json"):
        p.unlink()
    for f, plan in zip(floors, plans):
        (plans_dir / f"floor_{f.id}.json").write_text(json.dumps(plan_to_json(plan)), encoding="utf-8")
    exports = {"glb": glb.name}
    exp_cfg = cfg.get("export") or {}
    for fname in ("model_obj.zip", "model.ifc"):
        (out_dir / fname).unlink(missing_ok=True)        # never serve a stale export
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

    dbg = out_dir / "debug"
    if dbg.is_dir():                      # stale renders of a previous build
        for p in dbg.glob("*.png"):
            p.unlink()
    if debug_png:
        from .debug_plot import plot_overlay, plot_plan
        dbg.mkdir(exist_ok=True)
        for f, plan in zip(floors, plans):
            plot_plan(plan, dbg / f"floor_{f.id}.png", f"{f.name}  (elev {f.elevation} m, h {f.height} m)")
        plot_overlay([(f.name, p) for f, p in zip(floors, plans)], dbg / "overlay.png")

    top = floors[-1].elevation + floors[-1].height
    from shapely.ops import unary_union
    allfp = unary_union([p.footprint for p in plans if not p.footprint.is_empty])
    bx0, by0, bx1, by1 = allfp.bounds if not allfp.is_empty else (0, 0, 0, 0)
    quality = check_quality(floors, plans, sb.tri_count)
    # corrections re-anchored to the current floors: the caller persists these
    cfg["edits"], cfg["edits_unmatched"] = stored, unmatched
    meta = {
        **{k: v for k, v in info.items() if k != "layers"},
        "model": glb.name,
        "center": [round(c, 4) for c in center],
        "floors": floors_meta,
        "roof_node": roof_node,
        "entrances": entrances,
        "pois": pois,
        "room_types": legend(cfg),
        "height_range": [floors[0].elevation - cfg["building"]["slab_thickness"], top],
        # glTF X range and Z range (plan Y is flipped) of the model
        "extent": {"x": [round(bx0 - center[0], 2), round(bx1 - center[0], 2)],
                   "z": [round(center[1] - by1, 2), round(center[1] - by0, 2)]},
        "candidates": [{**c.to_dict(), "preview": candidate_preview(d, c)} for c in cands],
        "exports": exports,
        "layers": info["layers"],
        "triangles": sb.tri_count,
        "warnings": warnings,
        "quality": quality,
        "edits_unmatched": len(unmatched),
        "cache": {"floors_reused": n_cached, "floors": len(floors)},
        "elapsed_s": round(time.time() - t0, 2),
        "code_version": CODE_VERSION,
        "config": cfg,
    }
    (out_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    progress("done", 1.0, "Готово")
    return meta
