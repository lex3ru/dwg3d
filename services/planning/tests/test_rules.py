# ruff: noqa: E501
"""Places by rules, detectors by area, cameras' view and the checks of what stands where: the code counts,
nothing is placed; the administrator of the building asks, others are told nothing."""
from __future__ import annotations

from .conftest import API, BUILDING, CAMERA, CHAIR, DESK, DETECTOR, FLOOR, ROOM, ROOM2


async def test_places_along_walls_and_in_the_corners(client, tokens, world):
    boss = tokens.bearer("boss")
    r = await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "count": 4, "where": "along_wall"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["name"] == "Рабочий стол" and body["rooms"] == [{"room_id": ROOM, "name": "Кабинет", "floor_id": FLOOR, "placed": 4, "notes": []}]
    assert len(body["places"]) == 4 and all(0 < p["x"] < 6 and 0 < p["y"] < 4 and p["floor_id"] == FLOOR for p in body["places"])
    # backs to the walls: the first desks stand along the bottom wall, d/2 + 1 cm off it, facing into the room
    first = body["places"][0]
    assert abs(first["y"] - 0.36) < 0.02 and first["angle"] in (0.0, 180.0, 90.0, 270.0)
    # the doorway is kept free: no desk within the door's way (x 2.55..3.45, y up to 0.7)
    assert not any(2.4 < p["x"] < 3.6 and p["y"] < 0.8 for p in body["places"])
    corners = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": CHAIR, "floor_id": FLOOR, "count": 8, "where": "corners"})).json()
    # a corridor is not furnished by a floor-wide request; the room gets at most one chair a side
    assert [x["room_id"] for x in corners["rooms"]] == [ROOM] and corners["rooms"][0]["placed"] == 4 and "поместилось 4 из 8" in corners["rooms"][0]["notes"][0]


async def test_grid_avoids_what_stands_there(client, tokens, world):
    boss = tokens.bearer("boss")
    world.put(DESK, "СТ-1", 3, 2)                       # a desk in the middle
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "count": 3, "where": "center", "gap": 0.3})).json()
    assert r["rooms"][0]["placed"] == 3
    assert not any(abs(p["x"] - 3) < 0.9 and abs(p["y"] - 2) < 0.6 for p in r["places"])


async def test_detectors_by_area(client, tokens, world):
    boss = tokens.bearer("boss")
    r = await client.post(f"{API}/detectors", headers=boss, json={"building_id": BUILDING, "type_id": DETECTOR, "floor_id": FLOOR})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["radius"] == 5
    by = {x["room_id"]: x for x in body["rooms"]}
    # 24 m² and 9 m²: one detector each (0.7·π·25 ≈ 55 m² per detector)
    assert by[ROOM]["need"] == 1 and by[ROOM]["has"] == 0 and by[ROOM]["add"] == 1
    assert by[ROOM2]["need"] == 1 and len(body["places"]) == 2
    assert all(0.5 <= p["x"] <= 5.5 for p in body["places"])
    # one already there: nothing to add in that room
    world.put(DETECTOR, "ИЗ-1", 3, 2)
    body = (await client.post(f"{API}/detectors", headers=boss, json={"building_id": BUILDING, "type_id": DETECTOR, "room_ids": [ROOM]})).json()
    assert body["rooms"][0]["has"] == 1 and body["rooms"][0]["add"] == 0 and body["places"] == []
    # not a detector
    r = await client.post(f"{API}/detectors", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "floor_id": FLOOR})
    assert r.status_code == 422


async def test_cameras_and_checks(client, tokens, world):
    boss = tokens.bearer("boss")
    cov = (await client.get(f"{API}/coverage", headers=boss, params={"building_id": BUILDING, "floor_id": FLOOR})).json()
    assert cov["cameras"] == 0 and all(x["seen"] == 0 for x in cov["rooms"])
    cam = world.put(CAMERA, "К-1", 0.2, 0.2)
    world.touch(cam["id"], angle=135)                   # its front (sin a, −cos a) points into the room from the corner
    cov = (await client.get(f"{API}/coverage", headers=boss, params={"building_id": BUILDING, "floor_id": FLOOR})).json()
    office = next(x for x in cov["rooms"] if x["room_id"] == ROOM)
    assert cov["cameras"] == 1 and office["cameras"] == [cam["id"]] and 30 < office["seen"] <= 100 and 0 < office["identify"] < office["seen"]
    # checks: a desk in the doorway, a chair on the desk, a chair outside the walls; the corridor is no «empty room»
    world.put(DESK, "СТ-2", 3, 0.5)
    world.put(CHAIR, "КР-1", 3, 0.5)
    world.put(CHAIR, "КР-2", 9, 9)
    chk = (await client.get(f"{API}/checks", headers=boss, params={"building_id": BUILDING, "floor_id": FLOOR})).json()
    problems = {b["name"]: b["problems"] for b in chk["blocked"]}
    assert "мешает двери или проходу" in problems["Рабочий стол СТ-2"]
    assert any("налезает" in p for p in problems["Рабочий стол СТ-2"])
    assert "выходит за стены помещения" in problems["Кресло посетителя КР-2"]
    assert chk["empty"] == [] or all(e["room_id"] != ROOM2 for e in chk["empty"])
    assert chk["doors"] == [] and chk["counts"]["blocked"] == 3


async def test_only_the_administrator_asks(client, tokens, world):
    other = tokens.bearer("clerk")
    for r in (await client.post(f"{API}/placements", headers=other, json={"building_id": BUILDING, "type_id": DESK, "floor_id": FLOOR}),
              await client.get(f"{API}/checks", headers=other, params={"building_id": BUILDING, "floor_id": FLOOR})):
        assert r.status_code in (403, 404)
    boss = tokens.bearer("boss")
    assert (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK})).status_code == 422
    assert (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": ["nope"]})).status_code == 404
