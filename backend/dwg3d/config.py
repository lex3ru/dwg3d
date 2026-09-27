"""Pipeline configuration: YAML defaults + user overrides (deep-merged)."""
from __future__ import annotations

import copy
import fnmatch
import math
import json
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_config.yaml")

ROLE_ORDER = ("ignore", "walls", "columns", "windows", "doors", "rooms", "grid", "insulation", "stairs")


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(*overrides: dict | str | Path | None) -> dict:
    """Defaults, then each override (dict, or path to .yaml/.json) on top."""
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    for ov in overrides:
        if ov is None:
            continue
        if isinstance(ov, (str, Path)):
            p = Path(ov)
            text = p.read_text(encoding="utf-8")
            ov = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
        cfg = deep_merge(cfg, ov or {})
    return cfg


def _match(name: str, patterns: list[str]) -> bool:
    n = name.casefold()
    return any(fnmatch.fnmatchcase(n, p.casefold()) for p in patterns or [])


class LayerMapper:
    """Maps layer / block names to semantic roles using config patterns."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.layers = cfg.get("layers", {})
        self.blocks = cfg.get("blocks", {})
        self._cache: dict[str, str | None] = {}

    def layer_role(self, layer: str) -> str | None:
        if layer not in self._cache:
            role = None
            for r in ROLE_ORDER:
                if _match(layer, self.layers.get(r, [])):
                    role = r
                    break
            self._cache[layer] = role
        return self._cache[layer]

    def block_role(self, block: str) -> str | None:
        for r in ("doors", "windows", "grid"):
            if _match(block, self.blocks.get(r, [])):
                return r
        return None

    def is_floor_block(self, block: str) -> bool:
        return _match(block, self.blocks.get("floors", []))

    def is_partition(self, layer: str) -> bool:
        return _match(layer, (self.cfg.get("wall_types") or {}).get("partition", []))

    def is_vitrage(self, layer: str) -> bool:
        return _match(layer, (self.cfg.get("opening_types") or {}).get("vitrage", []))

    def is_label_layer(self, layer: str) -> bool:
        pats = self.layers.get("labels") or []
        return not pats or _match(layer, pats)


# ------------------------------------------------------------ validation ---
class ConfigError(ValueError):
    pass


# (min, max) for numeric settings; anything outside is a typo or an attack
_RANGES = {
    "geometry.snap_tolerance": (0, 0.5), "geometry.gap_tolerance": (0, 2),
    "geometry.min_wall_thickness": (0.001, 1), "geometry.max_wall_thickness": (0.01, 5),
    "geometry.default_wall_thickness": (0.01, 2), "geometry.arc_tolerance": (0.001, 1),
    "geometry.min_room_area": (0, 1000), "geometry.min_opening_width": (0.05, 20),
    "geometry.max_door_width": (0.3, 20), "geometry.max_window_width": (0.3, 50),
    "geometry.stair_min_treads": (2, 200),
    "building.floor_height": (1.5, 50), "building.slab_thickness": (0, 3),
    "building.door_height": (0.5, 20), "building.window_sill": (0, 20), "building.window_head": (0.3, 30),
    "building.vitrage_min_width": (0, 1000), "building.vitrage_head": (0, 10), "building.riser": (0.05, 0.5),
    "floors.cluster_gap": (0.05, 10000), "floors.min_cluster_ratio": (0, 1),
}
_ENUMS = {
    "units": ("auto", "mm", "cm", "dm", "m", "in", "ft"),
    "floors.mode": ("auto", "single", "clusters", "layouts", "blocks"),
    "floors.alignment": ("auto", "grid", "features", "bbox", "none"),
}
_EXTRA_TOP = {"edits_unmatched"}
MAX_EDITS_PER_FLOOR = 5000
MAX_PATTERNS = 5000


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _xy(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 2 and all(_num(c) and abs(c) < 1e7 for c in v)


def validate_config(cfg: dict) -> dict:
    """Check a full (merged) config against the defaults' structure.
    Raises ConfigError with a human-readable message."""
    default = load_config()

    def walk(v, ref, path):
        if isinstance(ref, dict) and path not in ("edits",):
            if not isinstance(v, dict):
                raise ConfigError(f"{path}: ожидается объект")
            for k, sub in v.items():
                p = f"{path}.{k}" if path else k
                if k not in ref:
                    if path == "" and k in _EXTRA_TOP:
                        continue
                    raise ConfigError(f"Неизвестный параметр: {p}")
                walk(sub, ref[k], p)
            return
        if path in _ENUMS:
            if v not in _ENUMS[path]:
                raise ConfigError(f"{path}: допустимо {', '.join(_ENUMS[path])}")
        elif isinstance(ref, bool):
            if not isinstance(v, bool):
                raise ConfigError(f"{path}: ожидается true/false")
        elif _num(ref):
            if not _num(v):
                raise ConfigError(f"{path}: ожидается число")
            lo, hi = _RANGES.get(path, (0, 1e4))
            if not lo <= v <= hi:
                raise ConfigError(f"{path}: значение {v} вне диапазона [{lo}, {hi}]")
        elif isinstance(ref, list):
            if not isinstance(v, list):
                raise ConfigError(f"{path}: ожидается список")
            if ref and all(_num(x) for x in ref):        # numeric range like [0.2, 0.42]
                if len(v) != len(ref) or not all(_num(x) and 0 <= x <= 1e4 for x in v):
                    raise ConfigError(f"{path}: ожидается [{', '.join(['число'] * len(ref))}]")
            elif path != "floors.items":
                if len(v) > MAX_PATTERNS or not all(isinstance(x, str) and len(x) <= 200 for x in v):
                    raise ConfigError(f"{path}: ожидается список строк")
        elif isinstance(ref, str) and not isinstance(v, str):
            raise ConfigError(f"{path}: ожидается строка")

    walk(cfg, default, "")
    for it in (cfg.get("floors") or {}).get("items") or []:
        if not isinstance(it, dict) or "candidate" not in it:
            raise ConfigError("floors.items: каждый элемент — объект с полем candidate")
        for k in ("height", "elevation"):
            if it.get(k) is not None and not _num(it[k]):
                raise ConfigError(f"floors.items.{k}: ожидается число")
        if it.get("height") is not None and not 1.0 <= it["height"] <= 50:
            raise ConfigError("floors.items.height: вне диапазона [1, 50]")
        if it.get("offset") is not None and not _xy(it["offset"]):
            raise ConfigError("floors.items.offset: ожидается [x, y]")
    edits = cfg.get("edits") or {}
    if not isinstance(edits, dict):
        raise ConfigError("edits: ожидается объект")
    for fid, e in edits.items():
        if not isinstance(e, dict):
            raise ConfigError(f"edits.{fid}: ожидается объект")
        n = 0
        for k, items in e.items():
            if k == "_anchor":
                continue
            if k not in ("add_walls", "erase_walls", "add_openings", "openings", "rooms") or not isinstance(items, list):
                raise ConfigError(f"edits.{fid}.{k}: неизвестный вид правки")
            n += len(items)
            for it in items:
                pts = [it.get(p) for p in ("a", "b", "at") if isinstance(it, dict) and p in it]
                if not isinstance(it, dict) or not pts or not all(_xy(p) for p in pts):
                    raise ConfigError(f"edits.{fid}.{k}: некорректные координаты")
                for w in ("thickness", "width"):
                    if it.get(w) is not None and not (_num(it[w]) and 0 < it[w] <= 5):
                        raise ConfigError(f"edits.{fid}.{k}.{w}: вне диапазона (0, 5]")
        if n > MAX_EDITS_PER_FLOOR:
            raise ConfigError(f"edits.{fid}: слишком много правок ({n})")
    return cfg
