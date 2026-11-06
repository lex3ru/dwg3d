"""Живые камеры: RTSP / HTTP / USB-камера (или видеофайл как имитация камеры).

Подсчёт идёт той же логикой, что и разбор файла (pipeline.count_events), но по скользящему
окну последних WINDOW_S секунд треков. Правилам нужен трек целиком (исчез в проёме, гашение
обрывов трека, топтание у линии), поэтому событие фиксируется, только когда ему не меньше
SETTLE_S секунд: к этому времени трек успевает закончиться, а спорные пары — погаситься.
Итог: счёт отстаёт от реальности на ~SETTLE_S секунд.

Все камеры обслуживает один поток инференса (LiveEngine): кадры камер собираются в пакет и
идут в модель через общую блокировку pipeline.detect_people.
"""
import collections
import os
import sqlite3
import threading
import time
from pathlib import Path

# RTSP по TCP: по UDP на загруженной сети кадры приходят битыми
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import pipeline  # noqa: E402
from render import IN_COLOR, OUT_COLOR, draw_doors, track_color  # noqa: E402
from track import tracker_step  # noqa: E402

PROC_FPS = 15            # сколько кадров в секунду обрабатываем с каждой камеры
WINDOW_S = 60            # окно треков, по которому пересчитываются события
SETTLE_S = 8             # событие фиксируется, когда ему столько секунд
COUNT_EVERY_S = 1.0      # как часто пересчитывать события
DUP_S = 1.0              # то же событие (трек, дверь, направление) ближе этого — дубль пересчёта
PREVIEW_EVERY_S = 0.2    # как часто обновлять кадр предпросмотра
PREVIEW_MAX_W = 960
OPEN_TIMEOUT_MS = 10000
BACKOFF_MAX_S = 30


# ---------------- источник кадров ----------------
def source_kind(src):
    src = src.strip()
    if src.isdigit():
        return "usb"
    if "://" in src:
        return "stream"
    return "file"


def open_capture(src):
    kind = source_kind(src)
    if kind == "usb":
        return cv2.VideoCapture(int(src))
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, OPEN_TIMEOUT_MS]
    return cv2.VideoCapture(src.strip(), cv2.CAP_FFMPEG, params)


def v4l2_caps(path):
    """Linux: {"card", "bus", "capture"} устройства /dev/videoN (VIDIOC_QUERYCAP) или None.
    У одной USB-камеры несколько узлов: часть отдаёт видео, часть — только метаданные."""
    try:
        import fcntl
        fd = os.open(str(path), os.O_RDWR | os.O_NONBLOCK)
    except (ImportError, OSError):
        return None
    try:
        buf = bytearray(104)  # struct v4l2_capability
        fcntl.ioctl(fd, 0x80685600, buf)  # VIDIOC_QUERYCAP
        card, bus = (bytes(buf[a:b]).split(b"\0")[0].decode(errors="replace") for a, b in ((16, 48), (48, 80)))
        device_caps = int.from_bytes(buf[88:92], "little")
        return {"card": card, "bus": bus, "capture": bool(device_caps & 0x1)}  # V4L2_CAP_VIDEO_CAPTURE
    except OSError:
        return None
    finally:
        os.close(fd)


def device_users(path):
    """Имена программ (кроме нас), у которых открыто устройство, — видно только свои процессы."""
    target, users = os.path.realpath(path), set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == os.getpid():
            continue
        try:
            if any(os.path.realpath(f"/proc/{pid}/fd/{fd}") == target for fd in os.listdir(f"/proc/{pid}/fd")):
                users.add(open(f"/proc/{pid}/comm").read().strip())
        except OSError:
            continue
    return sorted(users)


def usb_cameras():
    """USB-камеры, отдающие видео: [{index, name, main, busy}]. main=False — дополнительный
    поток той же камеры (например, ИК-камера ноутбука)."""
    out, seen_bus = [], set()
    devs = [p for p in Path("/dev").glob("video*") if p.name[5:].isdigit()]
    for p in sorted(devs, key=lambda p: int(p.name[5:])):
        caps = v4l2_caps(p)
        if not caps or not caps["capture"]:
            continue
        out.append({"index": int(p.name[5:]), "name": caps["card"].split(":")[0].strip(),
                    "main": caps["bus"] not in seen_bus, "busy": device_users(p)})
        seen_bus.add(caps["bus"])
    return out


def explain_failure(src):
    """Понятная причина, почему источник не открылся, или None, если причина не ясна."""
    if source_kind(src) == "usb":
        path = Path(f"/dev/video{int(src)}")
        if not path.exists():
            return f"Устройства {path} нет — выберите камеру из списка найденных."
        caps = v4l2_caps(path)
        if caps and not caps["capture"]:
            return f"{path} — служебное устройство камеры «{caps['card'].split(':')[0]}», видео не отдаёт. " \
                   "Выберите камеру из списка найденных."
        users = device_users(path)
        if users:
            return f"Камера {path} занята программой: {', '.join(users)}. Закройте её (например, " \
                   "вкладку браузера с видеозвонком) и попробуйте снова."
        return None
    if source_kind(src) == "file" and not Path(src.strip()).exists():
        return "Такого файла нет."
    return None


def grab_frame(src):
    """Один кадр источника (для разметки дверей) или None."""
    cap = open_capture(src)
    try:
        for _ in range(5):  # первые кадры потока бывают битыми
            ok, img = cap.read()
            if ok and img is not None:
                return img
        return None
    finally:
        cap.release()


class FrameSource(threading.Thread):
    """Читает источник в своём потоке и держит только последний кадр: если обработка не
    успевает, старые кадры выбрасываются, а не копятся в буфере (иначе растёт задержка).
    Файл проигрывается в реальном времени по кругу — имитация камеры для проверки."""

    def __init__(self, src):
        super().__init__(daemon=True)
        self.src, self.kind = src, source_kind(src)
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self.frame, self.t, self.seq = None, 0.0, 0
        self.state, self.message = "connecting", "подключение"
        self.src_fps = None

    def get(self):
        with self.lock:
            return self.frame, self.t, self.seq

    def stop(self):
        self.stop_ev.set()

    def _set(self, state, message):
        self.state, self.message = state, message

    def run(self):
        backoff = 1.0
        while not self.stop_ev.is_set():
            self._set("connecting", "подключение")
            cap = open_capture(self.src)
            if not cap.isOpened():
                cap.release()
                why = explain_failure(self.src) or "не удалось открыть источник"
                self._set("error", f"{why.rstrip('.')}; повтор через {backoff:.0f} с")
                self.stop_ev.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX_S)
                continue
            self.src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            t_start, i, eof = time.time(), 0, False
            while not self.stop_ev.is_set():
                ok, img = cap.read()
                if not ok or img is None:
                    eof = True
                    break
                with self.lock:
                    self.frame, self.t, self.seq = img, time.time(), self.seq + 1
                self._set("running", "работает")
                backoff = 1.0
                if self.kind == "file":  # проигрываем с исходной скоростью
                    i += 1
                    self.stop_ev.wait(max(0.0, t_start + i / self.src_fps - time.time()))
            cap.release()
            if self.stop_ev.is_set():
                break
            if eof and self.kind == "file":
                continue  # файл закончился — по кругу
            self._set("error", f"поток прервался, переподключение через {backoff:.0f} с")
            self.stop_ev.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_S)
        self._set("stopped", "остановлена")


# ---------------- журнал ----------------
class Store:
    """SQLite: настройки камер и журнал событий. Время событий — Unix-время (с)."""

    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, source TEXT NOT NULL,
                    doors TEXT NOT NULL, terminal INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, cam_id TEXT NOT NULL, door TEXT NOT NULL,
                    kind TEXT NOT NULL, ts REAL NOT NULL, track INTEGER);
                CREATE INDEX IF NOT EXISTS events_cam_ts ON events(cam_id, ts);
            """)

    def _q(self, sql, args=(), many=False):
        with self.lock, self.db:
            cur = self.db.executemany(sql, args) if many else self.db.execute(sql, args)
            return cur.fetchall()

    def cameras(self):
        return [dict(r) for r in self._q("SELECT * FROM cameras ORDER BY created")]

    def save_camera(self, cam):
        self._q("INSERT OR REPLACE INTO cameras (id, name, source, doors, terminal, enabled, created) "
                "VALUES (:id, :name, :source, :doors, :terminal, :enabled, :created)", cam)

    def set_enabled(self, cam_id, enabled):
        self._q("UPDATE cameras SET enabled=? WHERE id=?", (int(enabled), cam_id))

    def delete_camera(self, cam_id):
        self._q("DELETE FROM cameras WHERE id=?", (cam_id,))
        self._q("DELETE FROM events WHERE cam_id=?", (cam_id,))

    def add_events(self, cam_id, events):
        self._q("INSERT INTO events (cam_id, door, kind, ts, track) VALUES (?, ?, ?, ?, ?)",
                [(cam_id, e["door"], e["kind"], e["ts"], e["track"]) for e in events], many=True)

    def counts(self, cam_id, since):
        out = {}
        for r in self._q("SELECT door, kind, COUNT(*) n FROM events WHERE cam_id=? AND ts>=? GROUP BY door, kind",
                         (cam_id, since)):
            out.setdefault(r["door"], {"in": 0, "out": 0})[r["kind"]] = r["n"]
        return out

    def recent(self, cam_id, limit=20):
        return [dict(r) for r in self._q("SELECT door, kind, ts FROM events WHERE cam_id=? ORDER BY ts DESC LIMIT ?",
                                         (cam_id, limit))]

    def hourly(self, cam_id, since):
        """{час (начало, Unix-время): {"in": N, "out": M}} начиная с since."""
        out = {}
        for r in self._q("SELECT CAST((ts - ?) / 3600 AS INTEGER) h, kind, COUNT(*) n FROM events "
                         "WHERE cam_id=? AND ts>=? GROUP BY h, kind", (since, cam_id, since)):
            out.setdefault(since + 3600 * r["h"], {"in": 0, "out": 0})[r["kind"]] = r["n"]
        return out

    def events(self, cam_id, since, until):
        return [dict(r) for r in self._q("SELECT door, kind, ts, track FROM events WHERE cam_id=? AND ts>=? AND ts<? "
                                         "ORDER BY ts", (cam_id, since, until))]


def local_midnight(now=None):
    lt = time.localtime(now if now is not None else time.time())
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


# ---------------- камера ----------------
class LiveCamera:
    """Состояние одной камеры: трекер, окно треков, зафиксированные события, предпросмотр.
    process() и count() принимают время кадра явно — так их можно гонять по записанному
    видео с «ускоренным» временем (см. tests/test_live.py)."""

    def __init__(self, cfg, store=None):
        self.cfg, self.store = cfg, store
        self.source = None
        self.lock = threading.Lock()
        self.tracker = pipeline.new_tracker(PROC_FPS)
        self.rows = collections.deque()           # [frame, id, x, y, w, h, conf]
        self.t0 = None                            # время первого кадра: frame = (t - t0) * PROC_FPS
        self.meta = None
        self.last_f, self.last_t, self.last_seq = -1, 0.0, 0
        self.last_count_t = 0.0
        self.emitted = {}                         # (трек, дверь, направление) -> [кадры]
        self.proc_ts = collections.deque(maxlen=30)
        self.boxes, self.flashes = [], []
        self.preview, self.preview_t = None, 0.0
        self.raw = None
        self.error = None

    # --- жизненный цикл ---
    @property
    def running(self):
        return self.source is not None

    def start(self):
        if not self.source:
            self.source = FrameSource(self.cfg["source"])
            self.source.start()

    def stop(self):
        if self.source:
            self.source.stop()
            self.source = None

    def status(self):
        if self.error:
            return "error", self.error
        if not self.source:
            return "stopped", "остановлена"
        return self.source.state, self.source.message

    def proc_fps(self):
        ts = self.proc_ts
        return (len(ts) - 1) / (ts[-1] - ts[0]) if len(ts) > 1 and ts[-1] > ts[0] else 0.0

    # --- кадры ---
    def take_frame(self):
        """Новый кадр источника, если пора обрабатывать (не чаще PROC_FPS), иначе None."""
        if not self.source:
            return None
        frame, t, seq = self.source.get()
        if frame is None or seq == self.last_seq or t - self.last_t < 0.9 / PROC_FPS:
            return None
        self.last_seq = seq
        return frame, t

    def process(self, frame, t, tlwh, conf):
        """Кадр с детекциями -> шаг трекера, запись в окно, предпросмотр."""
        with self.lock:
            if self.t0 is None:
                self.t0 = t
                self.meta = {"fps": PROC_FPS, "width": frame.shape[1], "height": frame.shape[0]}
            f = int(round((t - self.t0) * PROC_FPS))
            if f <= self.last_f:
                return
            self.last_f, self.last_t = f, t
            self.proc_ts.append(t)
            self.boxes = tracker_step(self.tracker, tlwh, conf)
            self.rows.extend((f, *b) for b in self.boxes)
            self.raw = frame
        if t - self.preview_t >= PREVIEW_EVERY_S:
            self.preview = self._render_preview(frame, t)
            self.preview_t = t

    def count(self, now=None):
        """Пересчитать события по окну и зафиксировать созревшие. Возвращает новые события."""
        with self.lock:
            if self.t0 is None:
                return []
            now = self.last_t if now is None else now
            f_now = int(round((now - self.t0) * PROC_FPS))
            f_lo = max(0, f_now - WINDOW_S * PROC_FPS)
            while self.rows and self.rows[0][0] < f_lo:
                self.rows.popleft()
            if not self.rows:
                return []
            rows = np.array(self.rows, np.float32)
        rows[:, 0] -= f_lo  # окно начинается с «нулевого» кадра: трек, обрезанный окном, не даёт входа
        events, _ = pipeline.count_events(rows, self.cfg["doors"], self.meta, f_now - f_lo + 1,
                                          self.cfg.get("terminal", True))
        new = []
        settled = f_now - SETTLE_S * PROC_FPS
        for e in events:
            f = e["frame"] + f_lo
            if f > settled:
                continue
            seen = self.emitted.setdefault((e["track"], e["door"], e["kind"]), [])
            if any(abs(f - g) <= DUP_S * PROC_FPS for g in seen):
                continue
            seen.append(f)
            new.append({"door": e["door"], "kind": e["kind"], "track": e["track"], "frame": f,
                        "ts": self.t0 + f / PROC_FPS})
        # забываем события, выпавшие из окна: пересчитать их уже нельзя
        for k in [k for k, v in self.emitted.items() if max(v) < f_lo]:
            del self.emitted[k]
        if new:
            if self.store:
                self.store.add_events(self.cfg["id"], new)
            self.flashes += [(now, e) for e in new]
        return new

    # --- предпросмотр ---
    def _render_preview(self, frame, t):
        k = min(1.0, PREVIEW_MAX_W / frame.shape[1])
        img = cv2.resize(frame, None, fx=k, fy=k) if k < 1 else frame.copy()
        for tid, x, y, w, h, _ in self.boxes:
            cv2.rectangle(img, (int(x * k), int(y * k)), (int((x + w) * k), int((y + h) * k)), track_color(tid), 2)
        # Точка ног и последняя секунда пути у видимых сейчас людей (ADR-0029).
        trails = {box[0]: [] for box in self.boxes}
        for f, tid, x, y, w, h, _ in reversed(self.rows):
            if self.last_f - f > PROC_FPS:
                break
            if tid in trails:
                trails[tid].append((round((x + w / 2) * k), round((y + h) * k)))
        for tid, trail in trails.items():
            if trail:
                color = track_color(tid)
                cv2.polylines(img, [np.asarray(trail, np.int32)], False, color, 2)
                cv2.circle(img, trail[0], 4, color, -1)
        draw_doors(img, self.cfg["doors"], k, 2)
        self.flashes = [(t0, e) for t0, e in self.flashes if t - t0 < 3.0]
        for j, (_, e) in enumerate(self.flashes[-4:]):
            txt = f"{e['door']}: {'IN' if e['kind'] == 'in' else 'OUT'}"
            (tw, _), _ = cv2.getTextSize(txt, 0, 0.9, 2)
            cv2.putText(img, txt, (img.shape[1] - tw - 10, 34 + j * 32), 0, 0.9,
                        IN_COLOR if e["kind"] == "in" else OUT_COLOR, 2)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None


# ---------------- общий цикл инференса ----------------
class LiveEngine(threading.Thread):
    """Один поток на все камеры: собрать свежие кадры -> детекция пакетом -> трекер и счёт."""

    def __init__(self):
        super().__init__(daemon=True)
        self.cams = {}
        self.lock = threading.Lock()
        self.stop_ev = threading.Event()

    def add(self, cam):
        with self.lock:
            self.cams[cam.cfg["id"]] = cam

    def remove(self, cam_id):
        with self.lock:
            cam = self.cams.pop(cam_id, None)
        if cam:
            cam.stop()
        return cam

    def get(self, cam_id):
        return self.cams.get(cam_id)

    def run(self):
        while not self.stop_ev.is_set():
            with self.lock:
                cams = list(self.cams.values())
            batch = [(c, fr) for c in cams if (fr := c.take_frame())]
            if batch:
                try:
                    dets = pipeline.detect_people([fr for _, (fr, _t) in batch])
                    for (c, (fr, t)), (tlwh, conf) in zip(batch, dets):
                        c.process(fr, t, tlwh, conf)
                        c.error = None
                except Exception as e:  # noqa: BLE001 — камера не должна ронять остальные
                    for c, _ in batch:
                        c.error = f"ошибка обработки: {e}"
            now = time.time()
            for c in cams:
                if c.running and c.t0 is not None and now - c.last_count_t >= COUNT_EVERY_S:
                    c.last_count_t = now
                    try:
                        c.count()
                    except Exception as e:  # noqa: BLE001
                        c.error = f"ошибка подсчёта: {e}"
            if not batch:
                self.stop_ev.wait(0.01)
