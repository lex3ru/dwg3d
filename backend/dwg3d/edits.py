"""Manual corrections (2D-editor edits, floors.items) anchored to floor sheets.

Candidate ids (`c3`, `l0`, `b2`) are positional: they come from the order in
which sheets are detected, so a changed layer mapping, `cluster_gap` or a
better heuristic can renumber them. Edit coordinates are plan coordinates,
i.e. *after* cross-floor alignment, so a changed alignment moves them.

To survive both, every stored correction carries an `_anchor`: the sheet it
was made on (layout, floor-block handle, bbox in sheet coordinates - these do
not depend on detection order or alignment) and the alignment offset in
effect at the time. On each build the anchor is matched to the current
candidates, edits are re-keyed to the new id and shifted by the change of
offset. Corrections whose sheet can no longer be found are not applied to a
random floor: they are reported and kept aside (`edits_unmatched`).
"""
from __future__ import annotations

import copy
import logging

log = logging.getLogger(__name__)

EDIT_KEYS = ("add_walls", "erase_walls", "add_openings", "openings", "rooms")
_POINT_KEYS = ("a", "b", "at")
MIN_IOU = 0.5


def edit_lists(e: dict | None) -> dict:
    """Only the edit lists of a floor entry (drops `_anchor` and unknown keys)."""
    return {k: list((e or {}).get(k) or []) for k in EDIT_KEYS}


def has_edits(e: dict | None) -> bool:
    return any(edit_lists(e).values())


def anchor_of(c, with_offset: bool = True) -> dict:
    """Anchor of a floor candidate (object with id/space/owner/bbox/offset) or of its dict form."""
    get = (lambda k, d=None: c.get(k, d)) if isinstance(c, dict) else (lambda k, d=None: getattr(c, k, d))
    a = {"id": get("id"), "space": get("space", "Model"), "owner": get("owner"),
         "bbox": [round(float(v), 3) for v in get("bbox")], "name": get("name", "")}
    if with_offset:
        a["offset"] = [round(float(v), 4) for v in (get("offset") or (0.0, 0.0))]
    return a


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(anchor: dict, cands, prefer_id: str | None = None):
    """The candidate an anchor refers to, or None."""
    best, best_score = None, 0.0
    for c in cands:
        if c.space != anchor.get("space", "Model"):
            continue
        if anchor.get("owner") is not None or c.owner is not None:
            if c.owner != anchor.get("owner"):
                continue
            score = 2.0                       # same floor block: exact
        else:
            score = _iou(c.bbox, anchor["bbox"])
            if score < MIN_IOU:
                continue
        score += 1e-3 * (c.id == prefer_id)
        if score > best_score:
            best, best_score = c, score
    return best


def _shift(items: list, dx: float, dy: float) -> list:
    out = []
    for it in items:
        it = dict(it)
        for k in _POINT_KEYS:
            if k in it and it[k] is not None:
                it[k] = [round(float(it[k][0]) + dx, 4), round(float(it[k][1]) + dy, 4)]
        out.append(it)
    return out


def resolve_items(cfg: dict, cands) -> list[str]:
    """Re-key anchored `floors.items` to the current candidate ids (in place).
    Returns warnings."""
    warnings = []
    items = (cfg.get("floors") or {}).get("items") or []
    ids = {c.id for c in cands}
    kept = []
    for it in items:
        a = it.get("_anchor")
        if a:
            c = match(a, cands, prefer_id=str(it.get("candidate")))
            if c is None:
                warnings.append(f"Назначение этажа «{a.get('name') or it.get('candidate')}» не сопоставлено "
                                f"ни одному листу чертежа и не применено")
                continue
            it = {**it, "candidate": c.id, "_anchor": anchor_of(c, with_offset=False)}
        elif str(it.get("candidate")) in ids:
            c = next(c for c in cands if c.id == str(it.get("candidate")))
            it = {**it, "_anchor": anchor_of(c, with_offset=False)}
        kept.append(it)
    if items:
        cfg["floors"]["items"] = kept
    return warnings


def resolve_edits(cfg: dict, floors) -> tuple[dict, dict, list, list[str]]:
    """Map stored edits onto the current floors.

    Returns (applied, stored, unmatched, warnings):
      applied   {floor_id: edit lists in current plan coordinates}
      stored    {floor_id: {**lists, "_anchor": ...}} - what to persist
      unmatched [{"key", "_anchor", **lists}] - edits whose floor is gone
    """
    applied, stored, unmatched, warnings = {}, {}, [], []
    by_id = {f.id: f for f in floors}
    raw = cfg.get("edits") or {}
    # entries whose key is still valid go first, so they win conflicts
    for key, e in sorted(raw.items(), key=lambda kv: kv[0] not in by_id):
        lists = edit_lists(e)
        if not any(lists.values()):
            continue
        a = (e or {}).get("_anchor")
        if a:
            f = match(a, floors, prefer_id=key)
        else:
            f = by_id.get(key)                # legacy / hand-written: trust the id
        if f is None or f.id in applied:
            why = "лист не найден" if f is None else f"конфликт с правками этажа {f.id}"
            warnings.append(f"Правки этажа «{(a or {}).get('name') or key}» не применены: {why}")
            unmatched.append({"key": key, **({"_anchor": a} if a else {}), **lists})
            continue
        if a:
            ox, oy = a.get("offset") or (0.0, 0.0)
            dx, dy = f.offset[0] - ox, f.offset[1] - oy
            if abs(dx) > 1e-4 or abs(dy) > 1e-4:
                lists = {k: _shift(v, dx, dy) for k, v in lists.items()}
                log.info("edits %s -> %s shifted by (%.3f, %.3f)", key, f.id, dx, dy)
            if f.id != key:
                log.info("edits %s re-keyed to %s", key, f.id)
        applied[f.id] = lists
        stored[f.id] = {**copy.deepcopy(lists), "_anchor": anchor_of(f)}
    # previously unmatched edits stay aside, but get a new chance every build
    for u in cfg.get("edits_unmatched") or []:
        a = u.get("_anchor")
        f = match(a, floors, prefer_id=u.get("key")) if a else None
        lists = edit_lists(u)
        if f is not None and f.id not in applied:
            ox, oy = a.get("offset") or (0.0, 0.0)
            lists = {k: _shift(v, f.offset[0] - ox, f.offset[1] - oy) for k, v in lists.items()}
            applied[f.id] = lists
            stored[f.id] = {**copy.deepcopy(lists), "_anchor": anchor_of(f)}
        else:
            unmatched.append(u)
    return applied, stored, unmatched, warnings
