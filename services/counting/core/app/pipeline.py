"""Обработка одного видео: детекция → трекинг → события у дверей → размеченное видео.

Двери задаёт пользователь, двумя способами:
  * mode="line" — отрезок порога (p1, p2) и точка inside: сторона, куда «входят»;
  * mode="zone" — прямоугольник дверного проёма (углы p1, p2): появился в проёме — вход,
    исчез в проёме — выход (камера внутри помещения; invert=True меняет вход и выход местами).
Параметры логики и трекера — подобранные на DEV-наборах WiseNET (см. README).
"""
import csv
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from detect import CONF, boxes_tlwh  # noqa: E402
from events import Params, camera_events  # noqa: E402
from events_line import LineParams, line_events, make_line  # noqa: E402
from render import render, zone_xywh  # noqa: E402
from track import make_tracker, rows_to_tracks, tracker_step  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parent.parent / "yolo11n.pt"
# подобранные на DEV параметры (cache/results/yolo11n_640__high0.25_new0.5_buffer0.5*.json)
TRACKER = dict(high=0.25, low=0.1, new=0.5, match=0.8)
TRACK_BUFFER_S = 0.5
ZONE_PARAMS = dict(door_overlap=0.45, roi_expand=0.2, min_track_s=0.4, gap_s=0.5, scale_range=(0.35, 1.6))
LINE_PARAMS = dict(band=0.03, margin=0.15, near=0.4, far=0.4, min_track_s=0.4, dither_s=3.0,
                   scale=False, term_border=True)
BATCH = 8
TARGET_FPS = 15      # в быстром режиме обрабатываем примерно столько кадров в секунду
DETECT_SHARE = 0.85  # доля прогресса на первый проход (детекция и трекинг), остальное — запись видео

_model = None
_model_lock = threading.Lock()
# torch на CPU этой машины резко замедляется от параллельных вызовов, поэтому все
# потребители модели (разбор видео, живые камеры) идут через одну блокировку
_infer_lock = threading.Lock()


def get_model():
    global _model
    with _model_lock:
        if _model is None:
            from ultralytics import YOLO
            _model = YOLO(str(MODEL_PATH))
    return _model


def detect_people(frames):
    """Кадры BGR -> [(рамки [x, y, w, h], уверенности)] по кадру."""
    model = get_model()
    with _infer_lock:
        results = model.predict(frames, conf=CONF, classes=[0], verbose=False)
    return [boxes_tlwh(r) for r in results]


def new_tracker(fps):
    """ByteTrack с подобранными параметрами; fps — частота обрабатываемых кадров."""
    return make_tracker(TRACKER["high"], TRACKER["low"], TRACKER["new"], TRACK_BUFFER_S * fps, TRACKER["match"])


def probe(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ok, _ = cap.read()
    cap.release()
    if not ok or w == 0:
        return None
    return {"fps": float(fps), "n_frames": n, "width": w, "height": h, "duration": n / fps if fps else 0}


def frame_at(path, t):
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
    ok, img = cap.read()
    cap.release()
    return img if ok else None


def detect_and_track(path, meta, stride, progress):
    """Проход 1. Возвращает (rows [frame, id, x, y, w, h, conf], число прочитанных кадров).
    progress(доля 0..1, текст)."""
    tracker = new_tracker(meta["fps"] / stride)
    cap = cv2.VideoCapture(str(path))
    total = max(1, meta["n_frames"])
    rows, f, batch, idx = [], 0, [], []

    def flush():
        for i, (tlwh, conf) in zip(idx, detect_people(batch)):
            rows.extend((i, *r) for r in tracker_step(tracker, tlwh, conf))
        batch.clear()
        idx.clear()

    try:
        while True:
            ok, img = cap.read()
            if not ok:
                break
            if f % stride == 0:
                batch.append(img)
                idx.append(f)
                if len(batch) == BATCH:
                    flush()
                    progress(f / total, f"Поиск и сопровождение людей: кадр {f} из {total}")
            f += 1
        if batch:
            flush()
    finally:
        cap.release()
    return np.array(rows, np.float32).reshape(-1, 7), f


def zone_events(tracks, doors, fps, n_frames, W, H):
    """Логика «прямоугольник проёма» (events.camera_events) для дверей пользователя."""
    if not doors:
        return []
    cam = SimpleNamespace(cam=0, space="room", rois=[
        SimpleNamespace(roi=d["name"], door=d["name"], xywh=zone_xywh(d), other_space="door") for d in doors])
    invert = {d["name"]: d.get("invert", False) for d in doors}
    out = []
    for e in camera_events(tracks, cam, fps, n_frames, Params(**ZONE_PARAMS), (W, H)):
        kind = e["kind"]
        if invert[e["door"]]:
            kind = "out" if kind == "in" else "in"
        out.append({"door": e["door"], "kind": kind, "t": float(e["t"]), "frame": int(round(e["t"] * fps)),
                    "track": e["track"], "rule": "zone"})
    return out


def count_events(rows, doors, meta, n_frames, terminal=True):
    """Треки [frame, id, x, y, w, h, conf] -> (события у дверей по времени, число треков)."""
    tracks = rows_to_tracks(rows)
    fps, W, H = meta["fps"], meta["width"], meta["height"]
    lines = [make_line(d["name"], d["p1"], d["p2"], d["inside"]) for d in doors if d["mode"] == "line"]
    events = line_events(tracks, lines, fps, n_frames, W, H, LineParams(**LINE_PARAMS, use_terminal=terminal))
    events += zone_events(tracks, [d for d in doors if d["mode"] == "zone"], fps, n_frames, W, H)
    events.sort(key=lambda e: e["t"])
    return events, len(tracks)


def summarize(events, doors):
    """Счёт по дверям: {имя: {"in": N, "out": M}}."""
    summary = {d["name"]: {"in": 0, "out": 0} for d in doors}
    for e in events:
        summary[e["door"]][e["kind"]] += 1
    return summary


def process(path, meta, doors, out_dir, progress, terminal=True, fast=True):
    """doors: [{"name", "mode": "line"|"zone", "p1": [x, y], "p2": [x, y], "inside": [x, y], "invert": bool}]
    в пикселях исходного кадра."""
    out_dir = Path(out_dir)
    stride = max(1, round(meta["fps"] / TARGET_FPS)) if fast else 1
    rows, n_read = detect_and_track(path, meta, stride, lambda f, s: progress(DETECT_SHARE * f, s))
    meta = dict(meta, n_frames=n_read)
    progress(DETECT_SHARE, "Подсчёт проходов")
    events, n_tracks = count_events(rows, doors, meta, n_read, terminal)

    render(path, meta, rows, doors, events, out_dir / "annotated.mp4",
           lambda f, s: progress(DETECT_SHARE + (1 - DETECT_SHARE) * f, s), n_read, stride)

    summary = summarize(events, doors)
    with open(out_dir / "events.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "door", "direction", "track_id"])
        for e in events:
            w.writerow([f"{e['t']:.2f}", e["door"], "вход" if e["kind"] == "in" else "выход", e["track"]])
    result = {
        "summary": summary,
        "total": {"in": sum(v["in"] for v in summary.values()), "out": sum(v["out"] for v in summary.values())},
        "events": [{"t": round(e["t"], 2), "door": e["door"], "kind": e["kind"], "track": e["track"]} for e in events],
        "stride": stride, "tracks": n_tracks, "frames": n_read,
    }
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    progress(1.0, "Готово")
    return result
