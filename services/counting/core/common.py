"""Общее для исследовательских скриптов: пути, разбиение DEV/TEST, эталон, сохранённые результаты подбора."""
import json
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE.parent / "cache"
RESULTS = CACHE / "results"
# лучшие треки на DEV (см. README); от них отсчитываются compare_logic и приложение
BEST_RESULT = RESULTS / "yolo11n_640__high0.25_new0.5_buffer0.5"

DEV = [1, 3, 5, 6, 7]
TEST = [2, 4, 8, 9, 10, 11]


@lru_cache(maxsize=None)
def _gt_events():
    return tuple(json.loads((CACHE / "gt_events.json").read_text()))


def gt_events(set_id=None):
    """Эталонные события (из gt_events.py), все или одного набора."""
    return [g for g in _gt_events() if set_id is None or g["set"] == set_id]


def load_result(path):
    """Результат tune.py -> (имя треков, параметры логики Params | LineParams)."""
    from events import Params
    from events_line import LineParams

    R = json.loads(Path(path).read_text())
    pp = dict(R["params"], scale_range=tuple(R["params"]["scale_range"]))
    return R["tracks"], (LineParams if R.get("logic") == "line" else Params)(**pp)
