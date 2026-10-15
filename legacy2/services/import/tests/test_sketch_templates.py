# ruff: noqa: E501
"""Plans from a few words: the templates make plans the editor opens, with the rooms the words asked for."""
from __future__ import annotations

import pytest

from app.dwg.config import load_config
from app.sketch import plan_of, read_sketch
from app.sketch_check import check
from app.sketch_templates import TemplateError, make

from .test_sketches import API


def rooms_of(sketch: dict) -> list[tuple[str, float]]:
    plan = plan_of(read_sketch(sketch)["floors"][0], load_config({}))
    return sorted((r.name, round(r.area, 1)) for r in plan.rooms)


def test_a_corridor_with_rooms_on_both_sides():
    sketch, made = make("corridor", {"rooms_top": 3, "rooms_bottom": [4, 6], "room_width": 4, "room_depth": 5, "corridor_width": 2})
    assert made["rooms"] == 5 and made["length"] == 12 and made["depth"] == 12
    rooms = rooms_of(sketch)
    names = [n for n, _ in rooms]
    assert names.count("Коридор") == 1 and sum(1 for n in names if n.startswith("Кабинет")) == 5
    # a 4 × 5 room between a bearing wall (0.25) and partitions (0.12): about 3.8 × 4.8 m²
    assert any(n == "Кабинет 103" and 17 < a < 19.5 for n, a in rooms)
    # every room has a door, the outer rooms windows, the corridor an entrance
    kinds = [o["kind"] for o in sketch["floors"][0]["openings"].values()]
    assert kinds.count("door") == 6 and kinds.count("window") == 5
    # the editor's checks find nothing wrong
    issues = check(read_sketch(sketch))
    assert [i for i in issues if i["level"] == "error"] == []
    assert {i["code"] for i in issues} <= {"narrow-door"}


def test_one_sided_corridor_and_a_row():
    sketch, made = make("corridor", {"rooms": [3, 3, 3], "rooms_bottom": 0, "windows": False})
    assert made["rooms"] == 3
    assert [n for n, _ in rooms_of(sketch)] == ["Кабинет 101", "Кабинет 102", "Кабинет 103", "Коридор"]
    row, made = make("rooms_row", {"rooms": 2, "room_width": 6, "room_depth": 4, "room_name": "Гараж", "number_from": 1})
    assert made["rooms"] == 2 and [n for n, _ in rooms_of(row)] == ["Гараж 1", "Гараж 2"]


def test_open_space_with_meeting_rooms():
    sketch, made = make("open_space", {"length": 20, "width": 12, "meeting_rooms": [5, 5, 4], "meeting_depth": 4})
    assert made["meeting_rooms"] == 3
    rooms = rooms_of(sketch)
    hall = next(a for n, a in rooms if n == "Открытое пространство")
    assert 140 < hall < 160 and sum(1 for n, _ in rooms if n.startswith("Переговорная")) == 3
    assert check(read_sketch(sketch)) == [] or all(i["level"] != "error" for i in check(read_sketch(sketch)))


def test_bad_words_are_refused():
    with pytest.raises(TemplateError):
        make("corridor", {"rooms_top": 0, "rooms_bottom": 0})
    with pytest.raises(TemplateError):
        make("open_space", {"length": 10, "meeting_rooms": [6, 6]})
    with pytest.raises(TemplateError):
        make("tower", {})


async def test_by_request(client, tokens):
    r = await client.post(f"{API}/sketch-templates", json={"template": "corridor", "params": {"rooms": 2}}, headers=tokens.bearer("anyone"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["made"]["rooms"] == 2 and body["errors"] == 0 and body["summary"]["floors"][0]["rooms"]
    assert isinstance(body["sketch"]["floors"][0]["nodes"]["n1"], list)
    assert (await client.post(f"{API}/sketch-templates", json={"template": "corridor", "params": {"rooms": "много"}}, headers=tokens.bearer())).status_code == 422
