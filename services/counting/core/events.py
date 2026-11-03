"""Логика событий у двери для одной камеры.

Камера висит внутри помещения S и видит двери, ведущие в соседние помещения.
  * трек закончился у двери D (человек «растворился» в проёме) -> выход  S -> other(D)
  * трек начался у двери D (человек появился из проёма)          -> вход   other(D) -> S

Фильтры ложных срабатываний (каждый можно выключить для абляции):
  * traverse  — трек должен побывать и в комнате, а не только в зоне двери
                (иначе это человек по ту сторону проёма);
  * border    — рамка у края кадра, до которого дверь не доходит: человек вошёл/вышел
                за край кадра, а не через дверь;
  * occlusion — в момент начала/конца трека рамку закрывает другой человек: трек
                оборвался/возник из-за перекрытия;
  * foot      — ноги должны быть на уровне порога двери, а не ближе к камере;
  * scale     — высота человека сопоставима с высотой двери (дверь 2.04 м): отсекает
                далёких людей, попавших в зону близкой двери, и наоборот;
  * cancel    — «выход» и сразу «вход» у той же двери — обрыв трека.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class Params:
    door_overlap: float = 0.3   # доля рамки человека в (расширенной) зоне двери
    roi_expand: float = 0.15    # расширение зоны двери по каждой стороне, доля размера
    min_track_s: float = 0.6    # короче — шум
    edge_s: float = 0.5         # треки, начатые/законченные у границ видео, не считаем
    gap_s: float = 0.5          # разрыв в наблюдениях, после которого трек считается новым
    cancel_s: float = 2.0       # выход+вход у той же двери в пределах — обрыв трека
    traverse: bool = True
    outside_overlap: float = 0.1  # «в комнате» = перекрытие с зоной двери ниже этого
    border: bool = True
    border_px: float = 0.01     # доля размера кадра
    occlusion: bool = False     # в очередях у двери режет полноту сильнее, чем FP
    occl_frac: float = 0.5      # доля рамки, закрытая другой рамкой
    occl_window_s: float = 0.3
    foot: bool = True
    foot_tol: float = 0.25      # допуск ног ниже порога, доля высоты зоны двери
    scale: bool = True
    scale_range: tuple = (0.45, 1.5)  # высота рамки / высота двери


def split_by_gaps(frames, gap_frames):
    """Индексы начала/конца непрерывных кусков в отсортированном массиве кадров."""
    cuts = np.where(np.diff(frames) > gap_frames)[0]
    starts = np.r_[0, cuts + 1]
    ends = np.r_[cuts, len(frames) - 1]
    return list(zip(starts, ends))


def expand(roi, e):
    rx, ry, rw, rh = roi
    return rx - rw * e, ry - rh * e, rw * (1 + 2 * e), rh * (1 + 2 * e)


def cover_frac(box, other):
    """Доля площади box, покрытая other (обе в xywh)."""
    x, y, w, h = box
    ox, oy, ow, oh = other
    ix = max(0.0, min(x + w, ox + ow) - max(x, ox))
    iy = max(0.0, min(y + h, oy + oh) - max(y, oy))
    return ix * iy / max(w * h, 1e-6)


def scale_ok(box, roi, p):
    lo, hi = p.scale_range
    return lo <= box[3] / roi[3] <= hi


def door_at(box, cam, p):
    """Дверь, в зоне которой находится рамка (с наибольшим перекрытием), или None."""
    best, best_ov = None, p.door_overlap
    for r in cam.rois:
        if p.scale and not scale_ok(box, r.xywh, p):
            continue
        ov = cover_frac(box, expand(r.xywh, p.roi_expand))
        if ov >= best_ov:
            best, best_ov = r, ov
    return best


def touches_foreign_border(box, roi, W, H, p):
    """Рамка касается края кадра, до которого зона двери не доходит."""
    mx, my = W * p.border_px, H * p.border_px
    x, y, w, h = box
    rx, ry, rw, rh = expand(roi, p.roi_expand)
    for box_hit, roi_hit in (
        (x <= mx, rx <= mx),
        (x + w >= W - mx, rx + rw >= W - mx),
        (y <= my, ry <= my),
        (y + h >= H - my, ry + rh >= H - my),
    ):
        if box_hit and not roi_hit:
            return True
    return False


def foot_ok(box, roi, p):
    """Ноги не ниже порога двери (с допуском): иначе человек проходит перед дверью."""
    x, y, w, h = box
    rx, ry, rw, rh = roi
    return y + h <= ry + rh + p.foot_tol * rh


def camera_events(tracks, cam, fps, n_frames, p: Params, frame_size):
    """tracks: {track_id: np.array[[frame, x, y, w, h], ...]}, frame_size: (W, H).
    Возвращает список событий {door, from, to, t, cam, track, kind}."""
    W, H = frame_size
    # индекс рамок по кадрам для проверки перекрытий
    by_frame = {}
    segs = []
    for tid, arr in tracks.items():
        arr = arr[np.argsort(arr[:, 0])]
        for s, e in split_by_gaps(arr[:, 0], p.gap_s * fps):
            seg = arr[s:e + 1]
            key = (tid, int(s))
            segs.append((key, seg))
            for row in seg:
                by_frame.setdefault(int(row[0]), []).append((key, row[1:5]))

    def occluded(key, frame, box):
        w = int(p.occl_window_s * fps)
        for f in range(frame - w, frame + w + 1):
            for k2, b2 in by_frame.get(f, []):
                if k2 != key and cover_frac(box, b2) >= p.occl_frac:
                    return True
        return False

    raw = []
    for key, seg in segs:
        f0, f1 = seg[0, 0], seg[-1, 0]
        if (f1 - f0) / fps < p.min_track_s:
            continue
        for kind, idx, near_edge in (("in", 0, f0 / fps <= p.edge_s),
                                     ("out", -1, (n_frames - f1) / fps <= p.edge_s)):
            if near_edge:
                continue
            box = seg[idx, 1:5]
            r = door_at(box, cam, p)
            if r is None:
                continue
            if p.traverse and not any(cover_frac(b, expand(r.xywh, p.roi_expand)) < p.outside_overlap
                                      for b in seg[:, 1:5]):
                continue
            if p.border and touches_foreign_border(box, r.xywh, W, H, p):
                continue
            if p.foot and not foot_ok(box, r.xywh, p):
                continue
            if p.occlusion and occluded(key, int(seg[idx, 0]), box):
                continue
            a, b = (r.other_space, cam.space) if kind == "in" else (cam.space, r.other_space)
            raw.append({"door": r.door, "from": a, "to": b, "t": seg[idx, 0] / fps,
                        "kind": kind, "track": int(key[0])})

    raw.sort(key=lambda ev: ev["t"])
    dead = track_breaks(raw, p.cancel_s)
    return [dict(ev, cam=cam.cam) for k, ev in enumerate(raw) if k not in dead]


def track_breaks(raw, cancel_s, other_track=False):
    """Индексы пар «выход, затем вход» у той же двери не дальше cancel_s: это обрыв трека,
    а не два прохода. raw отсортирован по времени. other_track=True — только если «вход»
    дал другой трек (один и тот же трек туда-обратно — забота правила «топтания»)."""
    dead = set()
    for i, a in enumerate(raw):
        if a["kind"] != "out" or i in dead:
            continue
        for j in range(i + 1, len(raw)):
            b = raw[j]
            if b["t"] - a["t"] > cancel_s:
                break
            if (j not in dead and b["kind"] == "in" and b["door"] == a["door"]
                    and not (other_track and b["track"] == a["track"])):
                dead |= {i, j}
                break
    return dead
