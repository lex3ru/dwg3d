# ruff: noqa: E501
"""Plans drawn from a few words: a corridor with rooms on its sides, a row of rooms, an open space with meeting
rooms. The copilot fills the parameters from the description; the geometry is made here, so it is always a plan the
editor opens (nodes on a grid, walls between neighbours, doors into every room, labels inside the rooms).

Metres; the origin at the outer corner; Y up. Outer walls are bearing (0.25 m), inner ones partitions (0.12 m).
"""
from __future__ import annotations

from typing import Any

TEMPLATES = ("corridor", "rooms_row", "open_space")
OUTER, INNER = 0.25, 0.12
DOOR = {"kind": "door", "width": 0.9, "height": 2.1, "sill": 0.0, "hinge": "a", "side": "left"}
WINDOW = {"kind": "window", "width": 1.5, "height": 1.5, "sill": 0.8, "hinge": "a", "side": "left"}


class TemplateError(ValueError):
    pass


def _num(v, name: str, lo: float, hi: float, default: float) -> float:
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError) as ex:
        raise TemplateError(f"{name}: ожидалось число") from ex
    if not lo <= x <= hi:
        raise TemplateError(f"{name}: от {lo} до {hi}")
    return x


def _widths(v, name: str, count_default: int, width_default: float) -> list[float]:
    """A list of room widths, or a count with one width, or nothing (the default row)."""
    if v is None:
        return [width_default] * count_default
    if isinstance(v, int | float) and not isinstance(v, bool):
        n = int(v)
        if not 0 <= n <= 40:
            raise TemplateError(f"{name}: от 0 до 40 помещений")
        return [width_default] * n
    if isinstance(v, list):
        if len(v) > 40:
            raise TemplateError(f"{name}: не больше 40 помещений")
        return [_num(x, f"{name}[{i}]", 1.5, 30, width_default) for i, x in enumerate(v)]
    raise TemplateError(f"{name}: число помещений или список ширин")


class Grid:
    """Nodes by (x, y) made on demand, walls between them, openings and labels."""

    def __init__(self):
        self.nodes: dict[str, list[float]] = {}
        self.walls: dict[str, dict] = {}
        self.openings: dict[str, dict] = {}
        self.rooms: dict[str, dict] = {}
        self._at: dict[tuple[float, float], str] = {}

    def node(self, x: float, y: float) -> str:
        key = (round(x, 4), round(y, 4))
        if key not in self._at:
            nid = f"n{len(self._at) + 1}"
            self._at[key] = nid
            self.nodes[nid] = [key[0], key[1]]
        return self._at[key]

    def wall(self, a: tuple[float, float], b: tuple[float, float], kind: str = "partition") -> str:
        na, nb = self.node(*a), self.node(*b)
        if na == nb:
            raise TemplateError("стена нулевой длины")
        wid = f"w{len(self.walls) + 1}"
        self.walls[wid] = {"a": na, "b": nb, "thickness": OUTER if kind == "bearing" else INNER, "height": None, "kind": kind}
        return wid

    def opening(self, wall: str, at: float, spec: dict) -> None:
        self.openings[f"o{len(self.openings) + 1}"] = {"wall": wall, "at": round(at, 3), **spec}

    def finalize(self) -> None:
        """Every node lying on a wall splits it there: a wall ending on another is a joint, not a crossing."""
        import math
        changed = True
        while changed:
            changed = False
            for wid, w in list(self.walls.items()):
                a, b = self.nodes[w["a"]], self.nodes[w["b"]]
                length = math.dist(a, b)
                inside = []
                for nid, p in self.nodes.items():
                    if nid in (w["a"], w["b"]):
                        continue
                    da, db = math.dist(a, p), math.dist(p, b)
                    if abs(da + db - length) < 1e-6 and 1e-6 < da < length - 1e-6:
                        inside.append((da, nid))
                if not inside:
                    continue
                inside.sort()
                cut, nid = inside[0]
                second = f"{wid}s{len(self.walls)}"
                self.walls[second] = {**w, "a": nid, "b": w["b"]}
                w["b"] = nid
                for o in self.openings.values():
                    if o["wall"] == wid and o["at"] > cut:
                        o["wall"], o["at"] = second, round(o["at"] - cut, 3)
                changed = True

    def label(self, x: float, y: float, name: str, number: str, kind: str | None) -> None:
        self.rooms[f"r{len(self.rooms) + 1}"] = {"at": [round(x, 3), round(y, 3)], "name": name, "number": number, "type": kind}


def _row_of_rooms(g: Grid, widths: list[float], x0: float, y0: float, y1: float, door_y: float, number_from: int,
                  names: str, kind: str, windows_y: float | None, door_width: float) -> int:
    """Rooms side by side between y0 and y1; their doors on the wall at `door_y` (y0 or y1); windows on the other."""
    x = x0
    n = number_from
    for w in widths:
        # the wall with the door and the wall with the window, each only this room's stretch (the grid joins them)
        door_wall = g.wall((x, door_y), (x + w, door_y), "partition")
        g.opening(door_wall, w / 2, {**DOOR, "width": min(door_width, w - 0.4)})
        if windows_y is not None and w >= 2.2:
            win_wall = g.wall((x, windows_y), (x + w, windows_y), "bearing")
            g.opening(win_wall, w / 2, {**WINDOW, "width": min(WINDOW["width"], w - 0.8)})
        elif windows_y is not None:
            g.wall((x, windows_y), (x + w, windows_y), "bearing")
        g.label(x + w / 2, (y0 + y1) / 2, f"{names} {n}", str(n), kind)
        x += w
        n += 1
    return n


def corridor(p: dict[str, Any]) -> tuple[dict, dict]:
    """Rooms along both sides of a corridor (or one side): left — above, right — below the corridor."""
    cw = _num(p.get("corridor_width"), "corridor_width", 1.2, 6, 2.0)
    depth = _num(p.get("room_depth"), "room_depth", 2.5, 15, 5.0)
    width = _num(p.get("room_width"), "room_width", 1.5, 30, 4.0)
    top = _widths(p.get("rooms_top", p.get("rooms")), "rooms_top", 4, width)
    bottom = _widths(p.get("rooms_bottom"), "rooms_bottom", 0 if "rooms_bottom" not in p and "rooms" in p else 4, width)
    if not top and not bottom:
        raise TemplateError("нужно хотя бы одно помещение")
    height = _num(p.get("height"), "height", 2.4, 6, 3.0)
    length = max(sum(top), sum(bottom))
    windows = p.get("windows", True)
    door_width = _num(p.get("door_width"), "door_width", 0.7, 1.5, 0.9)
    g = Grid()
    y_bottom_outer = 0.0
    y_c0 = depth if bottom else 0.0                  # corridor bottom
    y_c1 = y_c0 + cw                                 # corridor top
    y_top_outer = y_c1 + (depth if top else 0.0)
    # outer walls: the right side whole, the left side in pieces round the corridor's end (the entrance is there);
    # the bottom and top edges come from the rooms (windows) or are plain
    if y_c0 > 0:
        g.wall((0, y_bottom_outer), (0, y_c0), "bearing")
    end = g.wall((0, y_c0), (0, y_c1), "bearing")
    if y_top_outer > y_c1:
        g.wall((0, y_c1), (0, y_top_outer), "bearing")
    g.wall((length, y_bottom_outer), (length, y_top_outer), "bearing")
    n = int(_num(p.get("number_from"), "number_from", 1, 9999, 101))
    names = str(p.get("room_name") or "Кабинет")[:40]
    kind = str(p.get("room_type") or "office")[:40]
    if bottom:
        n = _row_of_rooms(g, bottom, 0, y_bottom_outer, y_c0, y_c0, n, names, kind, y_bottom_outer if windows else None, door_width)
        if not windows:
            g.wall((0, y_bottom_outer), (length, y_bottom_outer), "bearing")
        if sum(bottom) < length:
            g.wall((sum(bottom), y_bottom_outer), (length, y_bottom_outer), "bearing")
            g.wall((sum(bottom), y_c0), (length, y_c0), "partition")
        # partitions between the rooms
        x = 0.0
        for w in bottom[:-1]:
            x += w
            g.wall((x, y_bottom_outer), (x, y_c0))
    else:
        g.wall((0, y_c0), (length, y_c0), "bearing")
    if top:
        n = _row_of_rooms(g, top, 0, y_c1, y_top_outer, y_c1, n, names, kind, y_top_outer if windows else None, door_width)
        if not windows:
            g.wall((0, y_top_outer), (length, y_top_outer), "bearing")
        if sum(top) < length:
            g.wall((sum(top), y_top_outer), (length, y_top_outer), "bearing")
            g.wall((sum(top), y_c1), (length, y_c1), "partition")
        x = 0.0
        for w in top[:-1]:
            x += w
            g.wall((x, y_c1), (x, y_top_outer))
    else:
        g.wall((0, y_c1), (length, y_c1), "bearing")
    g.label(length / 2, (y_c0 + y_c1) / 2, "Коридор", "", "corridor")
    # the entrance: a door at the corridor's end
    if p.get("entrance", True):
        g.opening(end, cw / 2, {**DOOR, "width": min(1.2, cw - 0.3)})
    return _sketch(g, height, p), {"template": "corridor", "length": round(length, 2), "depth": round(y_top_outer, 2),
                                   "rooms": len(top) + len(bottom), "corridor_width": cw}


def rooms_row(p: dict[str, Any]) -> tuple[dict, dict]:
    """Rooms in one row, doors on the front (bottom) wall, windows at the back."""
    depth = _num(p.get("room_depth"), "room_depth", 2.5, 15, 5.0)
    width = _num(p.get("room_width"), "room_width", 1.5, 30, 4.0)
    rooms = _widths(p.get("rooms"), "rooms", 4, width)
    if not rooms:
        raise TemplateError("нужно хотя бы одно помещение")
    height = _num(p.get("height"), "height", 2.4, 6, 3.0)
    length = sum(rooms)
    g = Grid()
    g.wall((0, 0), (0, depth), "bearing")
    g.wall((length, 0), (length, depth), "bearing")
    n = int(_num(p.get("number_from"), "number_from", 1, 9999, 1))
    _row_of_rooms(g, rooms, 0, 0, depth, 0, n, str(p.get("room_name") or "Помещение")[:40], str(p.get("room_type") or "office")[:40],
                  depth if p.get("windows", True) else None, _num(p.get("door_width"), "door_width", 0.7, 1.5, 0.9))
    if not p.get("windows", True):
        g.wall((0, depth), (length, depth), "bearing")
    x = 0.0
    for w in rooms[:-1]:
        x += w
        g.wall((x, 0), (x, depth))
    # the front wall is bearing too (the doors lead outside or to a hall)
    for wid, w in g.walls.items():
        a, b = g.nodes[w["a"]], g.nodes[w["b"]]
        if a[1] == 0 and b[1] == 0:
            g.walls[wid]["kind"], g.walls[wid]["thickness"] = "bearing", OUTER
    return _sketch(g, height, p), {"template": "rooms_row", "length": round(length, 2), "depth": depth, "rooms": len(rooms)}


def open_space(p: dict[str, Any]) -> tuple[dict, dict]:
    """A hall, with meeting rooms along its top side opening into it."""
    length = _num(p.get("length"), "length", 4, 80, 20.0)
    width = _num(p.get("width"), "width", 4, 40, 12.0)
    mdepth = _num(p.get("meeting_depth"), "meeting_depth", 2.5, 12, 4.0)
    meetings = _widths(p.get("meeting_rooms"), "meeting_rooms", 2, _num(p.get("meeting_width"), "meeting_width", 2, 20, 5.0))
    if sum(meetings) > length + 1e-6:
        raise TemplateError("переговорные не помещаются по длине зала")
    height = _num(p.get("height"), "height", 2.4, 6, 3.0)
    g = Grid()
    hall_top = width - (mdepth if meetings else 0)
    g.wall((0, 0), (length, 0), "bearing")
    g.wall((0, 0), (0, width), "bearing")
    g.wall((length, 0), (length, width), "bearing")
    if meetings:
        _row_of_rooms(g, meetings, 0, hall_top, width, hall_top, 1, "Переговорная", "meeting", width if p.get("windows", True) else None,
                      _num(p.get("door_width"), "door_width", 0.7, 1.5, 0.9))
        if not p.get("windows", True):
            g.wall((0, width), (length, width), "bearing")
        if sum(meetings) < length:
            g.wall((sum(meetings), width), (length, width), "bearing")
            g.wall((sum(meetings), hall_top), (length, hall_top), "partition")
        x = 0.0
        for w in meetings[:-1]:
            x += w
            g.wall((x, hall_top), (x, width))
    else:
        g.wall((0, width), (length, width), "bearing")
    g.label(length / 2, hall_top / 2, str(p.get("hall_name") or "Открытое пространство")[:40], "", "office")
    # the entrance: a door in the middle of the bottom wall
    bottom = next(wid for wid, w in g.walls.items() if g.nodes[w["a"]][1] == 0 and g.nodes[w["b"]][1] == 0)
    g.opening(bottom, length / 2, {**DOOR, "width": 1.2})
    return _sketch(g, height, p), {"template": "open_space", "length": length, "width": width, "meeting_rooms": len(meetings)}


def _sketch(g: Grid, height: float, p: dict) -> dict:
    g.finalize()
    return {"version": 1, "floors": [{"id": "f1", "name": str(p.get("floor_name") or "Этаж 1")[:60], "level": int(_num(p.get("level"), "level", -10, 300, 1)),
                                     "elevation": 0, "height": height, "nodes": g.nodes, "walls": g.walls, "openings": g.openings,
                                     "rooms": g.rooms, "columns": {}, "stairs": {}}]}


def make(template: str, params: dict[str, Any] | None) -> tuple[dict, dict]:
    p = params or {}
    if template == "corridor":
        return corridor(p)
    if template == "rooms_row":
        return rooms_row(p)
    if template == "open_space":
        return open_space(p)
    raise TemplateError(f"template: одно из {', '.join(TEMPLATES)}")
