"""Pipeline configuration: YAML defaults + user overrides (deep-merged)."""
from __future__ import annotations

import copy
import fnmatch
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
