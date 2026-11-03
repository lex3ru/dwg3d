"""Постоянный счётчик и надёжная доставка событий в приложение (ADR-0028)."""
import copy
import json
import os
import signal
import sqlite3
import sys
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

# RTSP-диагностика библиотек может содержать адрес с паролем (ADR-0028).
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"

sys.path.insert(0, str(Path(__file__).resolve().parent / "core/app"))
import live
import pipeline


class Outbox:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT)")

    def put(self, event):
        self.put_many([event])

    def put_many(self, events):
        with self.lock, self.db:
            self.db.executemany("INSERT INTO outbox VALUES (?,?)",
                                [(e["id"], json.dumps(e)) for e in events])

    def pending(self):
        with self.lock:
            return [json.loads(r[0]) for r in self.db.execute("SELECT body FROM outbox LIMIT 100")]

    def ack(self, ids):
        with self.lock, self.db:
            self.db.executemany("DELETE FROM outbox WHERE id=?", [(i,) for i in ids])


class Sink:
    def __init__(self, queue, config):
        self.queue, self.config = queue, config

    def add_events(self, cam_id, events):
        self.queue.put_many([{"id": str(uuid.uuid4()), "camera_id": cam_id,
                            "version": self.config["version"], "door": e["door"],
                            "direction": e["kind"],
                            "occurred_at": datetime.fromtimestamp(e["ts"], UTC).isoformat()}
                             for e in events])


class Camera(live.LiveCamera):
    def count(self, now=None):
        previous = copy.deepcopy(self.emitted)
        try:
            return super().count(now)
        except Exception:
            # При ошибке записи пачка откатывается и будет вычислена заново.
            self.emitted = previous
            raise

    def process(self, frame, t, tlwh, conf):
        # Нормированные координаты интерфейса переводим в пиксели исходного кадра.
        if self.t0 is None:
            h, w = frame.shape[:2]
            c = self.cfg["settings"]
            self.cfg["doors"] = [{"name": c["door"], "mode": "line",
                **{k: [c[k]["x"] * w, c[k]["y"] * h] for k in ("p1", "p2", "inside")}}]
        super().process(frame, t, tlwh, conf)


def main():
    url = os.environ["COUNTING_APP_URL"].rstrip("/")
    token = Path(os.environ["COUNTING_TOKEN_FILE"]).read_text().strip()
    if not token:
        raise SystemExit("Не задан служебный токен аналитики.")
    pipeline.MODEL_PATH = Path(os.environ.get("COUNTING_MODEL", "/models/yolo11n.pt"))
    if not pipeline.MODEL_PATH.is_file():
        raise SystemExit("Отсутствуют веса YOLO: задайте COUNTING_MODEL.")
    import torch
    torch.set_num_threads(2)
    queue = Outbox(os.environ.get("COUNTING_OUTBOX", "/data/outbox.db"))
    engine = live.LiveEngine()
    engine.start()
    print("Сервис подсчёта запущен", flush=True)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    def request(path, body=None):
        req = Request(url + "/api/surveillance/service/" + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                               "X-Requested-With": "app"})
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    last_status = 0
    try:
        while not stop.is_set():
            try:
                configs = request("config")["cameras"]
                desired = {c["id"]: c for c in configs}
                for cam_id in list(engine.cams):
                    old = engine.get(cam_id)
                    if cam_id not in desired or old.cfg["settings"] != desired[cam_id]:
                        engine.remove(cam_id)
                for c in configs:
                    if engine.get(c["id"]) is None:
                        cam = Camera({"id": c["id"], "source": c["source"], "settings": c,
                                      "doors": [], "terminal": False}, Sink(queue, c))
                        engine.add(cam)
                        cam.start()
            except (OSError, ValueError, KeyError):
                # Не выводим исключения транспорта: они могут содержать адреса и секреты.
                print("Не удалось синхронизировать настройки аналитики", flush=True)
            try:
                if time.monotonic() - last_status > 20:
                    for cam in list(engine.cams.values()):
                        state, _ = cam.status()
                        if state == "running" and (not cam.last_t or time.time()-cam.last_t > 30):
                            state = "connecting"
                        request("status", {"camera_id": cam.cfg["id"],
                                          "version": cam.cfg["settings"]["version"], "state": state})
                    last_status = time.monotonic()
                batch = queue.pending()
                if batch:
                    queue.ack(request("events", {"events": batch})["accepted"])
            except (OSError, ValueError, KeyError, sqlite3.Error):
                print("События сохранены в очереди; доставка будет повторена", flush=True)
            stop.wait(3)
    finally:
        engine.stop_ev.set()
        engine.join(timeout=30)
        for cam_id in list(engine.cams):
            engine.remove(cam_id)


if __name__ == "__main__":
    main()
