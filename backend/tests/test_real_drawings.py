"""Regression checks on real drawings (skipped when the files are absent).

Add a drawing by putting it next to the project and appending an entry with
the expected, hand-verified numbers. Ranges are deliberately loose: they catch
regressions (a heuristic change breaking another drawing), not pixel changes.
"""
from pathlib import Path

import pytest

from dwg3d.convert import find_libredwg, find_oda
from dwg3d.pipeline import run

ROOT = Path(__file__).resolve().parents[2]

CASES = [
    {
        "file": ROOT / "2022-06-02 - Поэтажные планы.dwg",
        "levels": [-1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "elevations": {1: -0.05, 2: 4.15, 3: 8.35, 8: 29.35, 12: 46.15},
        "per_floor": {                 # level: (min, max) for stats
            3: {"window": (15, 25), "door": (25, 45), "rooms": (18, 32), "stairs": (4, 10)},
            9: {"window": (14, 24), "door": (20, 36), "rooms": (15, 26)},
        },
    },
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["file"].name)
def test_real_drawing(case, tmp_path):
    if not case["file"].exists():
        pytest.skip("drawing not available")
    if case["file"].suffix.lower() == ".dwg" and not (find_oda() or find_libredwg()):
        pytest.skip("no DWG converter")
    meta = run(case["file"], tmp_path, {"export": {"ifc": False, "obj": False}}, debug_png=False)
    floors = {f["level"]: f for f in meta["floors"]}
    assert sorted(floors) == case["levels"]
    for lvl, e in case["elevations"].items():
        assert floors[lvl]["elevation"] == pytest.approx(e, abs=0.01)
    for lvl, exp in case["per_floor"].items():
        st = floors[lvl]["stats"]
        got = {**st["openings"], "rooms": st["rooms"], "stairs": st["stairs"]}
        for k, (lo, hi) in exp.items():
            assert lo <= got.get(k, 0) <= hi, f"level {lvl} {k}={got.get(k, 0)} not in [{lo}, {hi}]"
    # every floor was aligned by grid/column features, not the bbox fallback
    assert all("bbox" not in f["alignment"] for f in meta["floors"])
