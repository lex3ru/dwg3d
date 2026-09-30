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
from types import SimpleNamespace

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


# ---------------------------------------------------------------- viewer data
# Placed furniture and pins (markers, comments) live in the job's viewer
# settings and refer to floors by id. After every build they are carried over
# the same way as the edits: each old floor is matched to a new one by its
# sheet, positions follow the change of alignment offset (and, for pins in
# glTF coordinates, of the model centre and floor elevation). Furniture whose
# floor is gone is kept aside in `furniture_unplaced` and retried next build.

def _floor_ns(f: dict) -> SimpleNamespace:
    return SimpleNamespace(id=f["id"], space=f.get("space", "Model"), owner=f.get("owner"),
                           bbox=f.get("bbox") or [0, 0, 0, 0], offset=f.get("offset") or [0.0, 0.0],
                           elevation=float(f.get("elevation") or 0.0), name=f.get("name", ""))


def remap_view(view: dict | None, old: dict | None, new: dict) -> tuple[dict | None, list[str]]:
    """Carry furniture and pins of `view` from the build `old` to the build `new` (results)."""
    if not view or not old:
        return view, []
    oldf = {f["id"]: f for f in old.get("floors") or [] if f.get("bbox")}
    newf = [_floor_ns(f) for f in new.get("floors") or [] if f.get("bbox")]
    by_new = {f.id: f for f in newf}
    cache: dict = {}

    def target(fid: str):
        """(new floor, dx, dy, dz) for an old floor id, or None when its sheet is gone."""
        if fid not in cache:
            o = oldf.get(fid)
            if o is None:                     # unknown to the old build: trust the id
                f = by_new.get(fid)
                cache[fid] = (f, 0.0, 0.0, 0.0) if f else None
            else:
                f = match(anchor_of(o), newf, prefer_id=fid)
                oo = o.get("offset") or (0.0, 0.0)
                cache[fid] = None if f is None else (
                    f, f.offset[0] - oo[0], f.offset[1] - oo[1], f.elevation - float(o.get("elevation") or 0.0))
        return cache[fid]

    out = dict(view)
    placed, unplaced = [], []
    for it in view.get("furniture") or []:
        t = target(it.get("floor") or "")
        if t is None:
            o = oldf.get(it.get("floor") or "")
            unplaced.append({**it, "_anchor": anchor_of(o) if o else None})
            continue
        f, dx, dy, _ = t
        placed.append({**it, "floor": f.id, "at": [round(it["at"][0] + dx, 4), round(it["at"][1] + dy, 4)]})
    for u in view.get("furniture_unplaced") or []:
        a = u.get("_anchor")
        f = match(a, newf, prefer_id=u.get("floor")) if a else None
        if f is None:
            unplaced.append(u)
            continue
        ox, oy = a.get("offset") or (0.0, 0.0)
        it = {k: v for k, v in u.items() if k != "_anchor"}
        placed.append({**it, "floor": f.id, "at": [round(it["at"][0] + f.offset[0] - ox, 4), round(it["at"][1] + f.offset[1] - oy, 4)]})
    if "furniture" in view or placed:
        out["furniture"] = placed
    if unplaced:
        out["furniture_unplaced"] = unplaced
    else:
        out.pop("furniture_unplaced", None)

    # pins are in glTF coordinates: plan = (x + cx, -z + cy)
    ocx, ocy = old.get("center") or (0.0, 0.0)
    ncx, ncy = new.get("center") or (0.0, 0.0)
    for key in ("markers", "comments"):
        if key not in view:
            continue
        pins = []
        for p in view.get(key) or []:
            x, y, z = p["pos"]
            fid, dx, dy, dz = p.get("floor") or "", 0.0, 0.0, 0.0
            if fid:
                t = target(fid)
                if t is None:
                    fid = ""                  # keep it where it was, as a building-wide pin
                else:
                    fid, dx, dy, dz = t[0].id, t[1], t[2], t[3]
            px, py = x + ocx + dx, -z + ocy + dy
            pins.append({**p, "floor": fid, "pos": [round(px - ncx, 4), round(y + dz, 4), round(-(py - ncy), 4)]})
        out[key] = pins

    warnings = []
    if unplaced:
        names = sorted({(u.get("_anchor") or {}).get("name") or u.get("floor") or "?" for u in unplaced})
        warnings.append(f"Оборудование ({len(unplaced)} шт.) не привязано: этаж «{', '.join(names)}» не найден "
                        f"в новой сборке. Оно сохранено — перенесите его на этаж в панели «Мебель и оборудование»")
    moved = sum(1 for k, t in cache.items() if t and (t[0].id != k))
    if moved:
        log.info("viewer data: %d floor(s) re-keyed", moved)
    return out, warnings
