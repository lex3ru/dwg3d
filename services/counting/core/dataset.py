"""Загрузка датасета WiseNET: наборы, калибровка камер, топология дверей, разметка."""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent / "wisenet_dataset"

SPACES = {
    "IfcSpace_102572": "s1", "IfcSpace_23922": "s2", "IfcSpace_24737": "s3",
    "IfcSpace_23294": "s4", "IfcSpace_23494": "s5", "IfcSpace_25466": "s6",
}
DOORS = {
    "IfcDoor_589362": "d1", "IfcDoor_588559": "d2", "IfcDoor_588624": "d3",
    "IfcDoor_588754": "d4", "IfcDoor_589135": "d5", "IfcDoor_589198": "d6",
    "IfcDoor_588175": "d7",
}
# Какие помещения соединяет каждая дверь (извлечено из IFCRELSPACEBOUNDARY в I3M.ifc).
# "out" — помещение, которого нет в разметке (коридор за дверью d1).
DOOR_SPACES = {
    "d1": ("s1", "out"), "d2": ("s1", "s2"), "d3": ("s1", "s2"), "d4": ("s1", "s3"),
    "d5": ("s2", "s4"), "d6": ("s2", "s5"), "d7": ("s1", "s6"),
}


@dataclass
class DoorROI:
    roi: str          # "RegionOfInterest_5"
    door: str         # "d4"
    xywh: tuple       # в пикселях кадра
    other_space: str  # помещение по ту сторону двери


@dataclass
class Camera:
    cam: int
    space: str                       # помещение, в котором висит камера
    rois: list = field(default_factory=list)


@dataclass
class VideoSet:
    set_id: int
    fps: int
    width: int
    height: int
    t0: datetime
    cams: list  # номера камер (= номер видео в наборе)

    def video_path(self, cam: int) -> Path:
        return ROOT / "video_sets" / f"set_{self.set_id}" / f"video{self.set_id}_{cam}.avi"

    def calib_res(self) -> str:
        return f"{self.width}_{self.height}"


def parse_time(s: str) -> datetime:
    # в разметке встречаются опечатки вида "2017-04-24-T12:15:00.001Z"
    s = s.replace("-T", "T").rstrip("Z")
    return datetime.fromisoformat(s)


@lru_cache(maxsize=None)
def load_set(set_id: int) -> VideoSet:
    ini = (ROOT / "manual_annotations/people_tracking" / f"set_{set_id}" / "setinfo.ini").read_text()
    get = lambda k: re.search(rf"^{k}=(.*)$", ini, re.M).group(1).strip()
    seqs = [int(x) for x in get("sequences").strip("{}").split(",")]
    return VideoSet(set_id, int(get("frameRate")), int(get("imWidth")), int(get("imHeight")),
                    parse_time(get("initialTime")), seqs)


@lru_cache(maxsize=None)
def n_frames(set_id: int, cam: int) -> int:
    cap = cv2.VideoCapture(str(load_set(set_id).video_path(cam)))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


@lru_cache(maxsize=None)
def load_camera(res: str, cam: int) -> Camera:
    j = json.loads((ROOT / "network_enviroment/camera_calibration" / res / f"cam_{cam}.json").read_text())
    space = SPACES[j["isHostedBy"]]
    c = Camera(cam, space)
    for r in j.get("regionsOfInterest", []):
        door = DOORS[r["represents"]]
        a, b = DOOR_SPACES[door]
        c.rois.append(DoorROI(r["regionOfInterest"], door, tuple(r["xywh"]), b if a == space else a))
    return c


def all_set_ids():
    return list(range(1, 12))


def load_gt_tracks(set_id: int):
    """Эталонные треки по помещениям: {person_id: [(space, t_start_s, t_end_s), ...]}."""
    vs = load_set(set_id)
    g = json.loads((ROOT / "manual_annotations/people_tracking" / f"set_{set_id}" / "gt.json").read_text())
    out = {}
    for t in g["tracks"]:
        out[t["id"]] = [
            ("s" + tl["location"].split()[-1],
             (parse_time(tl["start"]) - vs.t0).total_seconds(),
             (parse_time(tl["end"]) - vs.t0).total_seconds())
            for tl in t["tracklets"]
        ]
    return out


def load_manual_detections(set_id: int, cam: int):
    """Ручная разметка детекций: список (frame, person_id, x, y, w, h, roi)."""
    p = ROOT / "manual_annotations/people_detection" / f"set_{set_id}" / f"video{set_id}_{cam}.json"
    if not p.exists():
        return []
    rows = []
    for fr in json.loads(p.read_text())["frames"]:
        for d in fr["detections"]:
            rows.append((fr["frameNumber"], d["id"], *d["xywh"], d["regionOfInterest"]))
    return rows
