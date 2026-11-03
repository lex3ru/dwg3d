"""Трекинг поверх кэша детекций (ByteTrack из ultralytics), без повторной детекции.

  python track.py --dets yolo11n_640 [--high 0.25 --low 0.1 --new 0.25 --buffer 1.0 --match 0.8]

Результат: cache/tracks/<dets>/set{S}_cam{C}.npy, строки [frame, track_id, x, y, w, h, conf].
"""
import argparse
import itertools
from types import SimpleNamespace

import numpy as np
from ultralytics.trackers.byte_tracker import BYTETracker

from common import CACHE
from dataset import all_set_ids, load_set, n_frames


class Dets:
    """Минимальный Results-подобный объект, который ест BYTETracker."""

    def __init__(self, tlwh, conf):
        self.conf = conf
        self.cls = np.zeros(len(conf), np.float32)
        self.xywh = np.c_[tlwh[:, :2] + tlwh[:, 2:] / 2, tlwh[:, 2:]] if len(conf) else np.zeros((0, 4), np.float32)

    def __len__(self):
        return len(self.conf)

    def __getitem__(self, m):
        d = Dets.__new__(Dets)
        d.conf, d.cls, d.xywh = self.conf[m], self.cls[m], self.xywh[m]
        return d


def make_tracker(high, low, new, buffer_frames, match=0.8):
    """buffer_frames — сколько обработанных кадров держать потерянный трек."""
    tracker = BYTETracker(SimpleNamespace(track_high_thresh=high, track_low_thresh=low, new_track_thresh=new,
                                          track_buffer=max(1, int(buffer_frames)), match_thresh=match,
                                          fuse_score=True))
    # Свой счётчик номеров у каждого трекера. В ultralytics счётчик общий на процесс, и каждый
    # новый BYTETracker сбрасывает его в ноль: при нескольких живых камерах (или камере и
    # разборе файла) новые люди получали бы номера ещё живых треков, и треки склеивались бы.
    ids = itertools.count(1)
    tracker.track_class = type("LocalSTrack", (tracker.track_class,), {"next_id": staticmethod(lambda: next(ids))})
    return tracker


def tracker_step(tracker, tlwh, conf):
    """Один кадр: детекции [x, y, w, h] (левый верх) -> [(track_id, x, y, w, h, score)].
    Берём исходную рамку детектора, а не сглаженную Калманом."""
    out = []
    for _x1, _y1, _x2, _y2, tid, score, _cls, idx in tracker.update(Dets(tlwh, conf)):
        x, y, w, h = tlwh[int(idx)]
        out.append((tid, x, y, w, h, score))
    return out


def rows_to_tracks(rows):
    """[frame, id, x, y, w, h, conf] -> {track_id: array[[frame, x, y, w, h]]}, кадры по возрастанию."""
    rows = rows[np.lexsort((rows[:, 0], rows[:, 1]))]
    ids, starts = np.unique(rows[:, 1], return_index=True)
    return {int(t): part[:, [0, 2, 3, 4, 5]] for t, part in zip(ids, np.split(rows, starts[1:]))}


def track_video(dets, n_frames, fps, cfg):
    """dets: [frame, x, y, w, h, conf]. Возвращает [frame, id, x, y, w, h, conf]."""
    tracker = make_tracker(cfg.high, cfg.low, cfg.new, cfg.buffer * fps, cfg.match)
    dets = dets[np.argsort(dets[:, 0], kind="stable")]
    bounds = np.searchsorted(dets[:, 0], np.arange(n_frames + 1))
    out = []
    for f in range(n_frames):
        d = dets[bounds[f]:bounds[f + 1]]
        out += [(f, *r) for r in tracker_step(tracker, d[:, 1:5], d[:, 5])]
    return np.array(out, np.float32).reshape(-1, 7)


def main(dets_name, cfg, sets=None, out_name=None):
    out_dir = CACHE / "tracks" / (out_name or dets_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in sets or all_set_ids():
        vs = load_set(s)
        for cam in vs.cams:
            p = CACHE / "dets" / dets_name / f"set{s}_cam{cam}.npy"
            dst = out_dir / f"set{s}_cam{cam}.npy"
            if not p.exists() or dst.exists():
                continue
            np.save(dst, track_video(np.load(p), n_frames(s, cam), vs.fps, cfg))
    return out_dir.name


def parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", default="yolo11n_640")
    ap.add_argument("--out")
    ap.add_argument("--high", type=float, default=0.25)
    ap.add_argument("--low", type=float, default=0.1)
    ap.add_argument("--new", type=float, default=0.25)
    ap.add_argument("--buffer", type=float, default=1.0, help="сколько секунд держать потерянный трек")
    ap.add_argument("--match", type=float, default=0.8)
    ap.add_argument("--sets", type=int, nargs="*")
    return ap


if __name__ == "__main__":
    a = parser().parse_args()
    print(main(a.dets, a, a.sets, a.out))
