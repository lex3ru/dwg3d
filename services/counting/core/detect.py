"""Детекция людей YOLO по всем видео, кэш сырых детекций.

  python detect.py --model yolo11n.pt --imgsz 640

Результат: cache/dets/<name>/set{S}_cam{C}.npy, строки [frame, x, y, w, h, conf] (x,y — левый верх).
"""
import argparse
import os
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from common import CACHE

BATCH = 8
CONF = 0.1  # низкий порог: слабые детекции нужны ByteTrack для второго этапа сопоставления


def boxes_tlwh(result):
    """Результат YOLO -> (рамки [x, y, w, h] с левым верхом, уверенности), float32."""
    xyxy, conf = result.boxes.xyxy.cpu().numpy(), result.boxes.conf.cpu().numpy()
    return np.c_[xyxy[:, :2], xyxy[:, 2:] - xyxy[:, :2]].astype(np.float32), conf.astype(np.float32)


def job(args):
    set_id, cam, model_name, imgsz, conf, out_dir, threads, max_frames = args
    out = out_dir / f"set{set_id}_cam{cam}.npy"
    if out.exists() and not max_frames:
        return f"set{set_id} cam{cam}: уже есть"
    # без этого пулы потоков OpenCV/OpenMP в параллельных процессах мешают друг другу
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = str(threads)
    import cv2
    import torch
    from ultralytics import YOLO

    from dataset import load_set

    cv2.setNumThreads(1)
    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:  # процесс пула переиспользуется — уже выставлено
        pass
    model = YOLO(model_name)
    cap = cv2.VideoCapture(str(load_set(set_id).video_path(cam)))
    total = max_frames or int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rows, f, t0 = [], 0, time.time()
    done = False
    while not done:
        batch = []
        while len(batch) < BATCH:
            ok, img = cap.read()
            if not ok or (max_frames and f + len(batch) >= max_frames):
                done = True
                break
            batch.append(img)
        if not batch:
            break
        for i, r in enumerate(model.predict(batch, imgsz=imgsz, conf=conf, classes=[0], verbose=False)):
            tlwh, c = boxes_tlwh(r)
            rows += [(f + i, *box, cc) for box, cc in zip(tlwh, c)]
        f += len(batch)
        if f % 1000 < BATCH:
            print(f"  set{set_id} cam{cam}: {f}/{total} ({f / (time.time() - t0):.1f} к/с)", flush=True)
    cap.release()
    dt = time.time() - t0
    arr = np.array(rows, np.float32).reshape(-1, 6)
    if not max_frames:
        np.save(out, arr)
    return f"set{set_id} cam{cam}: {f} кадров, {f / dt:.1f} к/с, {len(arr)} детекций"


if __name__ == "__main__":
    from dataset import all_set_ids, load_set

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--conf", type=float, default=CONF)
    ap.add_argument("--workers", type=int, default=1,
                    help="параллельные процессы; на этой машине >1 резко замедляет torch")
    ap.add_argument("--sets", type=int, nargs="*")
    ap.add_argument("--bench", type=int, default=0, help="только замер скорости на N кадрах")
    a = ap.parse_args()
    name = f"{Path(a.model).stem}_{a.imgsz}"
    out_dir = CACHE / "dets" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    threads = max(1, os.cpu_count() // a.workers)
    jobs = [(s, c, a.model, a.imgsz, a.conf, out_dir, threads, a.bench)
            for s in (a.sets or all_set_ids()) for c in load_set(s).cams]
    t0 = time.time()
    with Pool(a.workers) as pool:
        for msg in pool.imap_unordered(job, jobs):
            print(f"[{time.time() - t0:6.0f}s] {msg}", flush=True)
