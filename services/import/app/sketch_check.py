# ruff: noqa: E501
"""Problems of a drawn plan and their repair — the server's twin of frontend/src/plan/check.ts, with more:
loose ends near another wall, rooms without a name, labels in no room, numbers given twice, narrow doors,
bearing walls that do not stand on the ones below. The copilot asks for the issues, proposes the repair and
the user applies it; the editor shows its own issues as it draws.

An issue: {floor_id, level: error|warning, code, message, ids: [wall or opening or label ids], at?: [x, y]}.
"""
from __future__ import annotations

import json
import math
from typing import Any

from shapely.geometry import Point

from .dwg.config import load_config
from .sketch import _faces, outlines, plan_of

JOIN_TOL = 0.005        # a wall shorter than this is none (frontend/src/plan/graph.ts)
SNAP = 0.3              # a loose end this close to another wall is meant to touch it
NARROW_DOOR = 0.8       # m: a door narrower than this is a warning (evacuation)
BEARING_TOL = 0.15      # m: a bearing wall stands on the floor below within this

XY = tuple[float, float]

NAMES = {
    "short-wall": "Стена короче 5 мм", "twin-walls": "Две стены между одними и теми же точками",
    "crossing": "Стены пересекаются не в узле", "opening-off-wall": "Проём выходит за стену",
    "openings-overlap": "Проёмы налезают друг на друга", "opening-too-tall": "Проём выше стены",
    "loose-end": "Конец стены не примыкает к соседней стене", "unnamed-room": "Помещение без названия",
    "stray-label": "Название помещения стоит вне помещений", "duplicate-number": "Один номер у двух помещений",
    "narrow-door": "Дверь уже 80 см", "bearing-off": "Несущая стена не стоит на несущей стене этажа ниже",
}
FIXABLE = ("short-wall", "twin-walls", "opening-off-wall", "openings-overlap", "opening-too-tall", "loose-end", "stray-label")


def _issue(f: dict, level: str, code: str, ids: list[str], message: str | None = None, at: XY | None = None) -> dict:
    out = {"floor_id": f["id"], "level": level, "code": code, "message": message or NAMES[code], "ids": ids}
    if at is not None:
        out["at"] = [round(at[0], 3), round(at[1], 3)]
    return out


def _hit(a: XY, b: XY, c: XY, d: XY):
    """Where segments a→b and c→d cross: (s, u) along each, or None when parallel."""
    r, q = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
    den = r[0] * q[1] - r[1] * q[0]
    if abs(den) < 1e-12:
        return None
    w = (c[0] - a[0], c[1] - a[1])
    return (w[0] * q[1] - w[1] * q[0]) / den, (w[0] * r[1] - w[1] * r[0]) / den


def _project(p: XY, a: XY, b: XY) -> tuple[float, XY]:
    """Distance from p to segment a–b and the nearest point on it (within the segment)."""
    ab = (b[0] - a[0], b[1] - a[1])
    ln = ab[0] ** 2 + ab[1] ** 2
    t = 0.0 if ln < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1]) / ln))
    q = (a[0] + ab[0] * t, a[1] + ab[1] * t)
    return math.dist(p, q), q


def check_floor(f: dict, cfg: dict | None = None) -> list[dict]:
    """What is wrong with one floor (the editor's checks and the extra ones)."""
    issues: list[dict] = []
    nodes, walls = f["nodes"], f["walls"]
    items = list(walls.items())
    pairs: dict[str, str] = {}
    for wid, w in items:
        if math.dist(nodes[w["a"]], nodes[w["b"]]) <= JOIN_TOL:
            issues.append(_issue(f, "error", "short-wall", [wid], at=nodes[w["a"]]))
        key = "|".join(sorted((w["a"], w["b"])))
        if key in pairs:
            issues.append(_issue(f, "error", "twin-walls", [pairs[key], wid], at=nodes[w["a"]]))
        else:
            pairs[key] = wid
    for i in range(len(items)):
        x, w = items[i]
        for j in range(i + 1, len(items)):
            y, v = items[j]
            if {w["a"], w["b"]} & {v["a"], v["b"]}:
                continue
            a, b, c, d = nodes[w["a"]], nodes[w["b"]], nodes[v["a"]], nodes[v["b"]]
            hit = _hit(a, b, c, d)
            if hit is None:
                continue
            e1, e2 = JOIN_TOL / max(math.dist(a, b), 1e-9), JOIN_TOL / max(math.dist(c, d), 1e-9)
            if -e1 < hit[0] < 1 + e1 and -e2 < hit[1] < 1 + e2:
                at = (a[0] + (b[0] - a[0]) * hit[0], a[1] + (b[1] - a[1]) * hit[0])
                issues.append(_issue(f, "error", "crossing", [x, y], at=at))
    lines = outlines(f)
    by_wall: dict[str, list[str]] = {}
    for oid, o in f["openings"].items():
        by_wall.setdefault(o["wall"], []).append(oid)
    for wid, oids in by_wall.items():
        w = walls[wid]
        lo, hi = _faces(f, w, lines[wid])
        h = w["height"] if w["height"] is not None else f["height"]
        ordered = sorted(oids, key=lambda i: f["openings"][i]["at"])
        for oid in ordered:
            o = f["openings"][oid]
            mid = _along(f, w, o["at"])
            if o["at"] - o["width"] / 2 < lo - 1e-6 or o["at"] + o["width"] / 2 > hi + 1e-6:
                issues.append(_issue(f, "error", "opening-off-wall", [oid], at=mid))
            if o["sill"] + o["height"] > h + 1e-6:
                issues.append(_issue(f, "warning", "opening-too-tall", [oid], at=mid))
            if o["kind"] == "door" and o["width"] < NARROW_DOOR - 1e-6:
                issues.append(_issue(f, "warning", "narrow-door", [oid], f"Дверь {round(o['width'] * 100)} см: уже 80 см", at=mid))
        for p, q in zip(ordered, ordered[1:], strict=False):
            o1, o2 = f["openings"][p], f["openings"][q]
            if o1["at"] + o1["width"] / 2 > o2["at"] - o2["width"] / 2 + 1e-6:
                issues.append(_issue(f, "error", "openings-overlap", [p, q], at=_along(f, walls[wid], o2["at"])))
    # loose ends: a wall end that touches nothing, with another wall or node within reach
    degree: dict[str, int] = {}
    for w in walls.values():
        degree[w["a"]] = degree.get(w["a"], 0) + 1
        degree[w["b"]] = degree.get(w["b"], 0) + 1
    for wid, w in items:
        if math.dist(nodes[w["a"]], nodes[w["b"]]) <= JOIN_TOL:
            continue                                    # reported as short already; it goes, not snaps
        for end in ("a", "b"):
            n = w[end]
            if degree.get(n, 0) != 1:
                continue
            near = _nearest(f, n, wid)
            if near is not None:
                gap, _ = near
                issues.append(_issue(f, "warning", "loose-end", [wid], f"{NAMES['loose-end']} (зазор {round(gap * 100)} см)", at=nodes[n]))
    # rooms and labels
    numbers: dict[str, list[str]] = {}
    for lid, lb in f["rooms"].items():
        if lb["number"].strip():
            numbers.setdefault(lb["number"].strip(), []).append(lid)
    for number, ids in numbers.items():
        if len(ids) > 1:
            issues.append(_issue(f, "warning", "duplicate-number", ids, f"Номер «{number}» у {len(ids)} помещений", at=f["rooms"][ids[0]]["at"]))
    try:
        plan = plan_of(f, cfg or load_config({}))
    except Exception:                               # a broken floor: its geometry is reported above
        return issues
    used: set[str] = set()
    for r in plan.rooms:
        poly = r.poly if hasattr(r, "poly") else r.polygon
        inside = [lid for lid, lb in f["rooms"].items() if poly.contains(Point(lb["at"]))]
        used.update(inside)
        if not inside or not f["rooms"][inside[0]]["name"].strip():
            p = poly.representative_point()
            issues.append(_issue(f, "warning", "unnamed-room", inside[:1], f"Помещение {round(r.area, 1)} м² без названия", at=(p.x, p.y)))
    for lid in f["rooms"]:
        if lid not in used:
            issues.append(_issue(f, "warning", "stray-label", [lid], at=f["rooms"][lid]["at"]))
    return issues


def _along(f: dict, w: dict, at: float) -> XY:
    a, b = f["nodes"][w["a"]], f["nodes"][w["b"]]
    ln = math.dist(a, b) or 1.0
    return (a[0] + (b[0] - a[0]) * at / ln, a[1] + (b[1] - a[1]) * at / ln)


def _nearest(f: dict, node: str, own: str):
    """The nearest other node or wall within SNAP of a node: (gap, ("node", id) | ("wall", id, point))."""
    p = f["nodes"][node]
    best = None
    for nid, q in f["nodes"].items():
        if nid == node:
            continue
        d = math.dist(p, q)
        if JOIN_TOL < d <= SNAP and (best is None or d < best[0]):
            best = (d, ("node", nid))
    for wid, w in f["walls"].items():
        if wid == own or node in (w["a"], w["b"]):
            continue
        d, q = _project(p, f["nodes"][w["a"]], f["nodes"][w["b"]])
        if JOIN_TOL < d <= SNAP and (best is None or d < best[0] - 1e-9):
            best = (d, ("wall", wid, q))
    return best


def check(sketch: dict) -> list[dict]:
    """All floors, plus bearing walls not standing on the floor below."""
    cfg = load_config({})
    floors = sorted(sketch["floors"], key=lambda f: f["level"])
    issues: list[dict] = []
    for i, f in enumerate(floors):
        issues.extend(check_floor(f, cfg))
        if i == 0:
            continue
        below = floors[i - 1]
        under = [(below["nodes"][w["a"]], below["nodes"][w["b"]]) for w in below["walls"].values() if w["kind"] == "bearing"]
        if not under:
            continue
        for wid, w in f["walls"].items():
            if w["kind"] != "bearing" or w.get("curve"):
                continue
            ends = (f["nodes"][w["a"]], f["nodes"][w["b"]])
            if not all(any(_project(p, a, b)[0] <= BEARING_TOL for a, b in under) for p in ends):
                issues.append(_issue(f, "warning", "bearing-off", [wid], at=ends[0]))
    return issues


def summary(sketch: dict) -> dict:
    """The plan in numbers: for the copilot to describe it."""
    cfg = load_config({})
    floors = []
    for f in sorted(sketch["floors"], key=lambda x: x["level"]):
        try:
            rooms = [{"name": r.name, "number": r.number, "type": r.label_type, "area": round(r.area, 1)} for r in plan_of(f, cfg).rooms]
        except Exception:
            rooms = []
        kinds: dict[str, int] = {}
        for o in f["openings"].values():
            kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
        floors.append({"id": f["id"], "name": f["name"], "level": f["level"], "height": f["height"],
                       "walls": len(f["walls"]), "bearing": sum(1 for w in f["walls"].values() if w["kind"] == "bearing"),
                       "openings": kinds, "columns": len(f.get("columns") or {}), "stairs": len(f.get("stairs") or {}),
                       "rooms": rooms, "area": round(sum(r["area"] for r in rooms), 1),
                       "unnamed": sum(1 for r in rooms if not r["name"].strip())})
    return {"floors": floors}


# -------------------------------------------------------------------- repair ---
def repair(sketch: dict, codes: tuple[str, ...] | list[str] | None = None, floor_id: str | None = None) -> tuple[dict, list[dict]]:
    """A copy of the sketch with the fixable issues fixed: (sketch, what was fixed). Curved walls are left alone."""
    want = set(codes or FIXABLE) & set(FIXABLE)
    out = json.loads(json.dumps(sketch))              # a copy, and tuples back to lists as a plan is stored
    fixed: list[dict] = []
    for f in out["floors"]:
        if floor_id and f["id"] != floor_id:
            continue
        fixed.extend(_repair_floor(f, want))
    return out, fixed


def _drop_wall(f: dict, wid: str) -> None:
    f["walls"].pop(wid, None)
    for oid in [i for i, o in f["openings"].items() if o["wall"] == wid]:
        del f["openings"][oid]


def _merge_nodes(f: dict, gone: str, into: str) -> None:
    """Every wall at `gone` now stands at `into`; walls that collapse or double up go."""
    for wid, w in list(f["walls"].items()):
        for end in ("a", "b"):
            if w[end] == gone:
                w[end] = into
        if w["a"] == w["b"]:
            _drop_wall(f, wid)
    f["nodes"].pop(gone, None)
    seen: dict[str, str] = {}
    for wid, w in list(f["walls"].items()):
        key = "|".join(sorted((w["a"], w["b"])))
        if key in seen:
            _drop_wall(f, wid)
        else:
            seen[key] = wid
    _sweep_nodes(f)


def _sweep_nodes(f: dict) -> None:
    used = {n for w in f["walls"].values() for n in (w["a"], w["b"])}
    for n in [n for n in f["nodes"] if n not in used]:
        del f["nodes"][n]


def _new_id(f: dict, prefix: str) -> str:
    n = 1
    taken = set(f["nodes"]) | set(f["walls"]) | set(f["openings"]) | set(f["rooms"])
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"


def _repair_floor(f: dict, want: set[str]) -> list[dict]:
    fixed: list[dict] = []

    def done(code: str, ids: list[str], what: str) -> None:
        fixed.append({"floor_id": f["id"], "code": code, "ids": ids, "what": what})

    curved = {wid for wid, w in f["walls"].items() if w.get("curve")}
    if "twin-walls" in want:
        seen: dict[str, str] = {}
        for wid, w in list(f["walls"].items()):
            key = "|".join(sorted((w["a"], w["b"])))
            if key in seen and wid not in curved:
                _drop_wall(f, wid)
                done("twin-walls", [seen[key], wid], f"убрана вторая стена {wid}")
            else:
                seen.setdefault(key, wid)
    if "short-wall" in want:
        for wid, w in list(f["walls"].items()):
            if wid in f["walls"] and wid not in curved and math.dist(f["nodes"][w["a"]], f["nodes"][w["b"]]) <= JOIN_TOL:
                a, b = w["a"], w["b"]
                _drop_wall(f, wid)
                if a != b:
                    _merge_nodes(f, b, a)
                done("short-wall", [wid], f"стена {wid} убрана, её концы слиты")
    if "loose-end" in want:
        degree: dict[str, int] = {}
        for w in f["walls"].values():
            degree[w["a"]] = degree.get(w["a"], 0) + 1
            degree[w["b"]] = degree.get(w["b"], 0) + 1
        for wid, w in list(f["walls"].items()):
            if wid not in f["walls"] or wid in curved:
                continue
            for end in ("a", "b"):
                n = w[end]
                if degree.get(n, 0) != 1 or n not in f["nodes"]:
                    continue
                near = _nearest(f, n, wid)
                if near is None:
                    continue
                gap, target = near
                if target[0] == "node":
                    _merge_nodes(f, n, target[1])
                    done("loose-end", [wid], f"конец стены {wid} примкнул к узлу {target[1]} ({round(gap * 100)} см)")
                else:
                    other, q = target[1], target[2]
                    ow = f["walls"][other]
                    if other in curved:
                        continue
                    # split the other wall at the point, and move the loose end there
                    mid = _new_id(f, "n")
                    f["nodes"][mid] = [round(q[0], 4), round(q[1], 4)]
                    second = _new_id(f, "w")
                    f["walls"][second] = {**ow, "a": mid, "b": ow["b"]}
                    ow["b"] = mid
                    a0 = f["nodes"][ow["a"]]
                    cut = math.dist(a0, f["nodes"][mid])
                    for o in f["openings"].values():
                        if o["wall"] == other and o["at"] > cut:
                            o["wall"], o["at"] = second, o["at"] - cut
                    _merge_nodes(f, n, mid)
                    done("loose-end", [wid], f"конец стены {wid} примкнул к стене {other} ({round(gap * 100)} см)")
                degree = {}
                for x in f["walls"].values():
                    degree[x["a"]] = degree.get(x["a"], 0) + 1
                    degree[x["b"]] = degree.get(x["b"], 0) + 1
    lines = outlines(f) if f["walls"] else {}
    if "opening-off-wall" in want:
        for oid, o in list(f["openings"].items()):
            w = f["walls"].get(o["wall"])
            if w is None:
                continue
            lo, hi = _faces(f, w, lines[o["wall"]])
            if hi - lo < o["width"] + 1e-6:
                if hi - lo < 0.3:
                    del f["openings"][oid]
                    done("opening-off-wall", [oid], f"проём {oid} убран: стена короче него")
                    continue
                o["width"] = round(hi - lo - 0.02, 3)
                o["at"] = round((lo + hi) / 2, 3)
                done("opening-off-wall", [oid], f"проём {oid} сужен до стены")
            elif o["at"] - o["width"] / 2 < lo - 1e-6 or o["at"] + o["width"] / 2 > hi + 1e-6:
                o["at"] = round(min(max(o["at"], lo + o["width"] / 2), hi - o["width"] / 2), 3)
                done("opening-off-wall", [oid], f"проём {oid} сдвинут внутрь стены")
    if "openings-overlap" in want:
        by_wall: dict[str, list[str]] = {}
        for oid, o in f["openings"].items():
            by_wall.setdefault(o["wall"], []).append(oid)
        for wid, oids in by_wall.items():
            w = f["walls"][wid]
            lo, hi = _faces(f, w, lines[wid])
            ordered = sorted(oids, key=lambda i: f["openings"][i]["at"])
            for p, q in zip(ordered, ordered[1:], strict=False):
                o1, o2 = f["openings"][p], f["openings"][q]
                edge = o1["at"] + o1["width"] / 2
                if edge > o2["at"] - o2["width"] / 2 + 1e-6:
                    if edge + o2["width"] <= hi + 1e-6:
                        o2["at"] = round(edge + o2["width"] / 2 + 0.01, 3)
                        done("openings-overlap", [p, q], f"проём {q} сдвинут за проём {p}")
                    else:
                        del f["openings"][q]
                        done("openings-overlap", [p, q], f"проём {q} убран: не помещается рядом с {p}")
    if "opening-too-tall" in want:
        for oid, o in f["openings"].items():
            w = f["walls"][o["wall"]]
            h = w["height"] if w["height"] is not None else f["height"]
            if o["sill"] + o["height"] > h + 1e-6:
                o["height"] = round(max(0.1, h - o["sill"]), 3)
                done("opening-too-tall", [oid], f"проём {oid} понижен до высоты стены")
    if "stray-label" in want and f["walls"]:
        try:
            plan = plan_of(f, load_config({}))
        except Exception:
            plan = None
        if plan is not None:
            polys = [r.poly if hasattr(r, "poly") else r.polygon for r in plan.rooms]
            for lid, lb in list(f["rooms"].items()):
                if not any(p.contains(Point(lb["at"])) for p in polys):
                    del f["rooms"][lid]
                    done("stray-label", [lid], f"название «{lb['name']}» вне помещений убрано")
    return fixed


def issue_counts(issues: list[dict]) -> dict[str, Any]:
    return {"errors": sum(1 for i in issues if i["level"] == "error"), "warnings": sum(1 for i in issues if i["level"] == "warning")}
