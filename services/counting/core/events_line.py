"""Логика событий по линии порога (вместо прямоугольника двери).

Для каждой двери на камере задан отрезок порога на полу и сторона комнаты
(door_lines.json). Точка ног человека = середина нижней кромки рамки.
  * пересечение: ноги перешли со стороны комнаты на сторону двери -> выход,
    обратно -> вход. Сторона определяется с гистерезисом, чтобы дрожание рамки
    у линии не давало пар ложных событий;
  * обрыв у линии: трек закончился (начался) в полосе у линии со стороны комнаты,
    а до этого (после этого) человек был заметно глубже в комнате — значит, он
    скрылся в проёме (вышел из проёма), но пересечь линию видимым не успел.
Расстояния меряются в ростах человека в этой же точке кадра (высота его рамки):
это учитывает перспективу, и параметры одинаковы для близких, дальних и боковых дверей.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from events import split_by_gaps, track_breaks


@dataclass
class LineParams:
    band: float = 0.05          # гистерезис: |расстояние| до линии, в ростах человека
    margin: float = 0.3         # допуск за концы отрезка, доля длины отрезка
    near: float = 0.35          # «у линии» для обрыва трека, в ростах человека
    far: float = 0.5            # «глубже в комнате» для обрыва трека
    use_terminal: bool = True   # правило обрыва у линии
    smooth: int = 5             # медианное сглаживание точки ног, кадров
    min_track_s: float = 0.6
    edge_s: float = 0.5
    gap_s: float = 0.5
    cancel_s: float = 2.0
    dither_s: float = 0.0       # тот же человек пересёк линию туда и обратно быстрее — топтание, не проход
    scale: bool = True
    scale_range: tuple = (0.35, 1.6)
    term_border: bool = True    # обрыв у края кадра, до которого линия не доходит, — не проход
    border_px: float = 0.01


@lru_cache(maxsize=None)
def load_lines():
    """Разметка линий порога WiseNET: {разрешение: {камера: {дверь: {p1, p2, room}}}}."""
    return json.loads((Path(__file__).parent / "door_lines.json").read_text())


@dataclass
class DoorLine:
    door: str
    other_space: str | None
    p1: np.ndarray
    t: np.ndarray       # единичный вектор вдоль отрезка
    n: np.ndarray       # единичная нормаль в сторону комнаты
    length: float
    door_h: float | None  # высота двери в пикселях (для проверки масштаба), если известна


def make_line(door, p1, p2, room, other_space=None, door_h=None):
    """Линия порога по двум точкам и точке внутри помещения."""
    p1, p2, room = (np.asarray(v, float) for v in (p1, p2, room))
    t = (p2 - p1) / np.linalg.norm(p2 - p1)
    n = np.array([-t[1], t[0]])
    if np.dot(room - p1, n) < 0:
        n = -n
    return DoorLine(door, other_space, p1, t, n, float(np.linalg.norm(p2 - p1)), door_h)


def door_lines(cam, res):
    spec = load_lines()[res].get(str(cam.cam), {})
    return [make_line(r.door, spec[r.door]["p1"], spec[r.door]["p2"], spec[r.door]["room"],
                      r.other_space, float(r.xywh[3]))
            for r in cam.rois if r.door in spec]


def median_smooth(a, k):
    if k <= 1 or len(a) < k:
        return a
    pad = k // 2
    ap = np.pad(a, ((pad, pad), (0, 0)), mode="edge")
    return np.stack([np.median(ap[i:i + k], 0) for i in range(len(a))])


def at_foreign_border(box, L, W, H, p):
    """Рамка у края кадра, до которого отрезок порога (с допуском) не доходит."""
    x, y, w, h = box
    mx, my = W * p.border_px, H * p.border_px
    ends = np.array([L.p1 - L.t * L.length * p.margin, L.p1 + L.t * L.length * (1 + p.margin)])
    for box_hit, line_hit in ((x <= mx, ends[:, 0].min() <= mx),
                              (x + w >= W - mx, ends[:, 0].max() >= W - mx),
                              (y <= my, ends[:, 1].min() <= my),
                              (y + h >= H - my, ends[:, 1].max() >= H - my)):
        if box_hit and not line_hit:
            return True
    return False


def line_events(tracks, lines, fps, n_frames, W, H, p: LineParams):
    """Ядро логики: tracks {id: [[frame, x, y, w, h], ...]}, lines [DoorLine].
    Возвращает события {door, kind: in|out, t, frame, track, rule}."""
    raw = []
    for tid, arr in tracks.items():
        arr = arr[np.argsort(arr[:, 0])]
        for s, e in split_by_gaps(arr[:, 0], p.gap_s * fps):
            seg = arr[s:e + 1]
            if (seg[-1, 0] - seg[0, 0]) / fps < p.min_track_s:
                continue
            frames = seg[:, 0]
            foot = median_smooth(np.c_[seg[:, 1] + seg[:, 3] / 2, seg[:, 2] + seg[:, 4]], p.smooth)
            heights = median_smooth(seg[:, 4:5], p.smooth)[:, 0]
            starts_mid = frames[0] / fps > p.edge_s
            ends_mid = (n_frames - frames[-1]) / fps > p.edge_s
            for L in lines:
                d = (foot - L.p1) @ L.n / heights            # >0 — сторона комнаты
                u = (foot - L.p1) @ L.t / L.length           # 0..1 — в пределах отрезка
                on_seg = (u >= -p.margin) & (u <= 1 + p.margin)

                def ok_scale(i):
                    lo, hi = p.scale_range
                    return not p.scale or L.door_h is None or lo <= heights[i] / L.door_h <= hi

                def emit(kind, i, rule):
                    raw.append({"door": L.door, "kind": kind, "t": float(frames[i] / fps),
                                "frame": int(frames[i]), "track": int(tid), "rule": rule})

                # 1) пересечения с гистерезисом
                side = 0
                for i in range(len(d)):
                    new = 1 if d[i] > p.band else (-1 if d[i] < -p.band else side)
                    if side and new != side and on_seg[i] and ok_scale(i):
                        emit("out" if new < 0 else "in", i, "cross")
                    side = new
                if not p.use_terminal:
                    continue
                # 2) обрыв у линии со стороны комнаты, а до/после — глубже в комнате.
                # Если человек уже пересёк линию видимым, трек кончается по ту сторону
                # (d < -band) и сюда не попадает — двойного счёта нет.
                last = len(d) - 1
                if (ends_mid and -p.band <= d[last] <= p.near and on_seg[last] and ok_scale(last)
                        and d.max() >= p.far
                        and not (p.term_border and at_foreign_border(seg[last, 1:5], L, W, H, p))):
                    emit("out", last, "term")
                if (starts_mid and -p.band <= d[0] <= p.near and on_seg[0] and ok_scale(0)
                        and d.max() >= p.far
                        and not (p.term_border and at_foreign_border(seg[0, 1:5], L, W, H, p))):
                    emit("in", 0, "term")

    # гасим пары «выход, затем вход» у той же двери с разных треков — обрыв трека
    raw.sort(key=lambda ev: ev["t"])
    dead = track_breaks(raw, p.cancel_s, other_track=True)
    # гасим «туда-обратно» одного и того же трека у той же двери: человек топчется у линии
    if p.dither_s > 0:
        last = {}  # (трек, дверь) -> индекс последнего живого события
        for i, ev in enumerate(raw):
            if i in dead:
                continue
            key = (ev["track"], ev["door"])
            j = last.get(key)
            if j is not None and raw[j]["kind"] != ev["kind"] and ev["t"] - raw[j]["t"] <= p.dither_s:
                dead |= {i, j}
                last.pop(key)
            else:
                last[key] = i
    return [ev for k, ev in enumerate(raw) if k not in dead]


def camera_events_line(tracks, cam, fps, n_frames, p: LineParams, res):
    """Обёртка для датасета: добавляет помещения «откуда/куда» и номер камеры."""
    lines = {L.door: L for L in door_lines(cam, res)}
    W, H = map(int, res.split("_"))
    out = []
    for ev in line_events(tracks, list(lines.values()), fps, n_frames, W, H, p):
        other = lines[ev["door"]].other_space
        a, b = (other, cam.space) if ev["kind"] == "in" else (cam.space, other)
        out.append(dict(ev, **{"from": a, "to": b, "cam": cam.cam}))
    return out
