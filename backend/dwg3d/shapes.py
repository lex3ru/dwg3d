"""Functional layers: routes of people and zones.

A route (geom "route") is a sequence of stops — a point on a floor, possibly
a room — in props.stops; the way between them (along corridors, through
doors, by stairs or lifts between floors) is computed by the viewer (A* over
the plan, see frontend/src/viewer/route.ts) and kept in props as a cache:
path (per floor segment), length (m), time (s), floors changed, the build it
was computed on, and a problem when no way was found. A route belongs to a
flow (patients, staff, clean, dirty...); some flows must not cross, and some
must not enter some zones — the rules are here and in /api/layer-kinds, the
viewer checks them.

A zone (geom "polygon") is an area of a floor of a kind (clean, dirty,
restricted...).

Clients give floors of stops and path segments by the candidate id of the
build they show (c0, c3...); rows keep floor row ids, which survive rebuilds.
"""
from __future__ import annotations

FLOWS = {
    "patients": {"name": "Пациенты", "color": "#1c7ed6"},
    "staff": {"name": "Персонал", "color": "#2f9e44"},
    "visitors": {"name": "Посетители", "color": "#7048e8"},
    "clean": {"name": "Чистый поток", "color": "#15aabf"},
    "dirty": {"name": "Грязный поток", "color": "#e8590c"},
    "infectious": {"name": "Инфекционные пациенты", "color": "#e03131"},
    "goods": {"name": "Грузы, снабжение", "color": "#868e96"},
}
# flows whose ways must not cross (the order in a pair does not matter)
FLOW_CONFLICTS = [("clean", "dirty"), ("patients", "dirty"), ("visitors", "dirty"), ("patients", "infectious"),
                  ("visitors", "infectious"), ("staff", "infectious")]
ZONE_KINDS = {
    "clean": {"name": "Чистая зона", "color": "#15aabf"},
    "dirty": {"name": "Грязная зона", "color": "#e8590c"},
    "restricted": {"name": "Доступ ограничен", "color": "#c92a2a"},
    "sterile": {"name": "Стерильная зона", "color": "#0ca678"},
    "other": {"name": "Другая", "color": "#868e96"},
}
# flows that must not enter zones of a kind
ZONE_FORBIDDEN = {"clean": ["dirty", "infectious"], "sterile": ["dirty", "infectious", "visitors", "goods"],
                  "restricted": ["patients", "visitors"]}
MAX_STOPS = 50
MAX_SEGMENTS = 100
MAX_PATH_POINTS = 20000


class ShapeError(ValueError):
    pass


def rules_json() -> dict:
    return {"flows": FLOWS, "flow_conflicts": FLOW_CONFLICTS, "zone_kinds": ZONE_KINDS,
            "zone_forbidden": ZONE_FORBIDDEN}


def _num(v, lo, hi, name) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ShapeError(f"{name}: ожидается число в [{lo}, {hi}]")
    return float(v)


def _xy(v, name) -> list[float]:
    if not isinstance(v, list) or len(v) != 2:
        raise ShapeError(f"{name}: ожидается [x, y]")
    return [_num(c, -1e5, 1e5, name) for c in v]


def _text(v, name, n) -> str:
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > n:
        raise ShapeError(f"{name}: строка до {n} символов")
    return v


def route_props(props: dict, floor_id) -> dict:
    """Validate the props of a route; `floor_id(cand)` turns a floor candidate
    id into the floor row id (raising for an unknown one)."""
    flow = props.get("flow") or "patients"
    if flow not in FLOWS:
        raise ShapeError(f"flow: {', '.join(FLOWS)}")
    stops = props.get("stops")
    if not isinstance(stops, list) or not 2 <= len(stops) <= MAX_STOPS:
        raise ShapeError(f"stops: от 2 до {MAX_STOPS} остановок {{floor, at: [x, y], room?, label?}}")
    out_stops = []
    for k, st in enumerate(stops):
        if not isinstance(st, dict):
            raise ShapeError("stops: остановка {floor, at: [x, y], room?, label?}")
        room = st.get("room")
        if room is not None and (isinstance(room, bool) or not isinstance(room, int)):
            raise ShapeError("stops.room: id помещения")
        out_stops.append({"floor": floor_id(str(st.get("floor") or "")), "at": _xy(st.get("at"), f"stops[{k}].at"),
                          "room": room, "label": _text(st.get("label"), "stops.label", 120)})
    out = {"flow": flow, "name": _text(props.get("name"), "name", 200), "stops": out_stops}
    if props.get("path") is not None:           # the computed way (a cache)
        path = props["path"]
        if not isinstance(path, list) or len(path) > MAX_SEGMENTS:
            raise ShapeError(f"path: до {MAX_SEGMENTS} участков {{floor, pts}}")
        segs, n = [], 0
        for sg in path:
            if not isinstance(sg, dict) or not isinstance(sg.get("pts"), list):
                raise ShapeError("path: участок {floor, pts: [[x, y], ...]}")
            n += len(sg["pts"])
            if n > MAX_PATH_POINTS:
                raise ShapeError(f"path: не больше {MAX_PATH_POINTS} точек")
            segs.append({"floor": floor_id(str(sg.get("floor") or "")), "pts": [_xy(p, "path.pts") for p in sg["pts"]]})
        out["path"] = segs
        for key, hi in (("length", 1e6), ("time", 1e7)):
            if props.get(key) is not None:
                out[key] = _num(props[key], 0, hi, key)
        if props.get("floors_changed") is not None:
            out["floors_changed"] = int(_num(props["floors_changed"], 0, 1000, "floors_changed"))
        if props.get("build") is not None:
            out["build"] = int(_num(props["build"], 0, 1e9, "build"))
    if props.get("problem"):
        out["problem"] = _text(props["problem"], "problem", 500)
    return out


def route_props_json(props: dict, cand) -> dict:
    """Stored route props as the client sees them (`cand(floor row id)` -> candidate id)."""
    out = dict(props)
    out["stops"] = [{**st, "floor": cand(st.get("floor"))} for st in props.get("stops") or []]
    if props.get("path") is not None:
        out["path"] = [{**sg, "floor": cand(sg.get("floor"))} for sg in props["path"]]
    return out


def zone_props(props: dict) -> dict:
    kind = props.get("zone") or "other"
    if kind not in ZONE_KINDS:
        raise ShapeError(f"zone: {', '.join(ZONE_KINDS)}")
    return {"zone": kind, "name": _text(props.get("name"), "name", 200)}


def shift_route(props: dict, moves: dict[int, tuple[float, float, float]]) -> dict | None:
    """Route props with stops and path moved with their floors (None: nothing moved)."""
    changed = False

    def mv(floor, pts):
        nonlocal changed
        dx, dy, _ = moves.get(floor, (0.0, 0.0, 0.0))
        if dx or dy:
            changed = True
            return [[x + dx, y + dy] for x, y in pts]
        return pts

    stops = [{**st, "at": mv(st.get("floor"), [st["at"]])[0]} for st in props.get("stops") or []]
    out = {**props, "stops": stops}
    if props.get("path") is not None:
        out["path"] = [{**sg, "pts": mv(sg.get("floor"), sg["pts"])} for sg in props["path"]]
    return out if changed else None
