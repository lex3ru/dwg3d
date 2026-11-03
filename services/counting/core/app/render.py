"""Размеченное видео H.264: рамки людей, двери, счётчики и всплывающие события."""
import subprocess

import cv2
import imageio_ffmpeg

from events_line import make_line

OUT_MAX_W = 1280                    # ширина размеченного видео
DOOR_COLOR = (40, 40, 255)          # BGR
IN_COLOR, OUT_COLOR = (80, 220, 80), (60, 140, 255)
FLASH_S = 1.2                       # сколько секунд висит надпись о событии


def zone_xywh(d):
    """Прямоугольник двери пользователя по двум углам -> (x, y, w, h)."""
    (x1, y1), (x2, y2) = d["p1"], d["p2"]
    return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)


def track_color(tid):
    return int(tid * 37) % 200 + 55, int(tid * 91) % 200 + 55, int(tid * 173) % 200 + 55


class FfmpegWriter:
    """Пишет кадры BGR в mp4 (H.264, faststart — чтобы браузер играл до полной загрузки)."""

    def __init__(self, path, size, fps):
        w, h = size
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(path)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, img):
        self.proc.stdin.write(img.tobytes())

    def close(self):
        self.proc.stdin.close()
        err = self.proc.stderr.read().decode(errors="replace").strip()
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg не смог записать видео: {err[-300:]}")

    def kill(self):
        self.proc.kill()
        self.proc.wait()


def draw_doors(img, doors, k, th):
    for d in doors:
        if d["mode"] == "zone":
            x, y, w, h = (v * k for v in zone_xywh(d))
            cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), DOOR_COLOR, th + 1)
            cv2.putText(img, d["name"], (int(x) + 4, int(y) - 8), 0, 0.7, DOOR_COLOR, 2)
            continue
        p1 = (int(d["p1"][0] * k), int(d["p1"][1] * k))
        p2 = (int(d["p2"][0] * k), int(d["p2"][1] * k))
        n = make_line(d["name"], d["p1"], d["p2"], d["inside"]).n
        mid = ((p1[0] + p2[0]) // 2, (p1[1] + p2[1]) // 2)
        cv2.line(img, p1, p2, DOOR_COLOR, th + 2)
        cv2.arrowedLine(img, mid, (int(mid[0] + n[0] * 40), int(mid[1] + n[1] * 40)), IN_COLOR, th + 1, tipLength=0.35)
        cv2.putText(img, d["name"], (p1[0] + 4, p1[1] - 8), 0, 0.7, DOOR_COLOR, 2)


def render(path, meta, rows, doors, events, out_path, progress, n_read, stride):
    """Второй проход по видео. rows — [frame, id, x, y, w, h, conf] обработанных кадров;
    на пропущенных в быстром режиме кадрах рисуем рамки последнего обработанного."""
    W, H, fps = meta["width"], meta["height"], meta["fps"]
    k = min(1.0, OUT_MAX_W / W)
    ow, oh = int(W * k) // 2 * 2, int(H * k) // 2 * 2
    th = 2

    boxes_at = {}
    for fr, tid, x, y, w, h, _ in rows:
        boxes_at.setdefault(int(fr), []).append((int(tid), x, y, w, h))
    ev_at = {}
    for e in events:
        ev_at.setdefault(e["frame"], []).append(e)
    counts = {d["name"]: {"in": 0, "out": 0} for d in doors}
    flashes, last_boxes = [], []
    pad, lh = 10, 28
    panel_w = max(330, 12 * max(len(d["name"]) for d in doors) + 190) if doors else 330

    cap = cv2.VideoCapture(str(path))
    out = FfmpegWriter(out_path, (ow, oh), fps)
    try:
        f = 0
        while f < n_read:
            ok, img = cap.read()
            if not ok:
                break
            if (ow, oh) != (W, H):
                img = cv2.resize(img, (ow, oh))
            if f % stride == 0:  # на обработанных кадрах обновляем рамки (в т.ч. на пустые)
                last_boxes = boxes_at.get(f, [])
            for tid, x, y, w, h in last_boxes:
                cv2.rectangle(img, (int(x * k), int(y * k)), (int((x + w) * k), int((y + h) * k)), track_color(tid), th)
            draw_doors(img, doors, k, th)
            for e in ev_at.get(f, []):
                counts[e["door"]][e["kind"]] += 1
                flashes.append((f, e))
            flashes = [(f0, e) for f0, e in flashes if f - f0 < fps * FLASH_S]

            cv2.rectangle(img, (0, 0), (min(panel_w, ow), pad * 2 + lh * len(doors)), (20, 20, 20), -1)
            for i, d in enumerate(doors):
                c = counts[d["name"]]
                cv2.putText(img, f"{d['name']}: in {c['in']}  out {c['out']}", (pad, pad + lh * (i + 1) - 8),
                            0, 0.7, (255, 255, 255), 2)
            for j, (_, e) in enumerate(flashes):
                txt = f"{e['door']}: {'IN' if e['kind'] == 'in' else 'OUT'}"
                (tw, _), _ = cv2.getTextSize(txt, 0, 1.0, 3)
                cv2.putText(img, txt, (max(0, ow - tw - 12), 40 + j * 36), 0, 1.0,
                            IN_COLOR if e["kind"] == "in" else OUT_COLOR, 3)
            out.write(img)
            f += 1
            if f % 50 == 0:
                progress(f / max(1, n_read), f"Запись размеченного видео: кадр {f} из {n_read}")
    except BaseException:
        out.kill()
        raise
    finally:
        cap.release()
    out.close()
