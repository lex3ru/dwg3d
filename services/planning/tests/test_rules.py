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


async def test_wall_mounted_things_avoid_openings_and_chairs_face_the_desk(client, tokens, world):
    boss = tokens.bearer("boss")
    SCREEN = "screen-type"
    world.types[SCREEN] = {"id": SCREEN, "name": "Экран", "category_id": "o", "price": None, "currency": "RUB", "size": [1.2, 0.1, 0.7],
                           "elevation": 1.5, "wall_mounted": True, "values": {}}
    # asked for the centre, a screen still goes to a wall — and not over the door at x 2.55..3.45 of the bottom wall
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": SCREEN, "room_ids": [ROOM], "count": 1, "where": "center"})).json()
    assert r["rooms"][0]["placed"] == 1 and "настенный" in r["rooms"][0]["notes"][0]
    p = r["places"][0]
    assert not (2.3 < p["x"] < 3.7 and p["y"] < 0.5)
    assert p["y"] < 0.2 or p["y"] > 3.8 or p["x"] < 0.2 or p["x"] > 5.8
    # chairs in front of a desk, looking at it
    desk = world.put(DESK, "СТ-9", 3, 3.5)
    world.touch(desk["id"], angle=0)                       # its front (sin a, −cos a) = (0, −1) points into the room
    r = await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": CHAIR, "count": 2, "where": "front_of", "anchor_asset_id": desk["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rooms"] and body["rooms"][0]["room_id"] == ROOM and body["rooms"][0]["placed"] == 2
    for c in body["places"]:
        assert c["angle"] == 180.0 and 2.4 < c["y"] < 3.2 and 2.0 < c["x"] < 4.0
    assert (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": CHAIR, "where": "front_of"})).status_code == 422


async def test_lights_are_spread_over_the_room(client, tokens, world):
    boss = tokens.bearer("boss")
    LIGHT = "light-type"
    world.types[LIGHT] = {"id": LIGHT, "name": "Светильник", "category_id": "l", "price": None, "currency": "RUB", "size": [0.6, 0.6, 0.05],
                          "elevation": 2.7, "ceiling_mounted": True, "values": {"light_flux": 3600}}
    for where in ("grid", "center"):
        r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": LIGHT, "room_ids": [ROOM], "count": 4, "where": where})).json()
        assert r["rooms"][0]["placed"] == 4, r
        xs = sorted({p["x"] for p in r["places"]})
        ys = sorted({p["y"] for p in r["places"]})
        # the 6 × 4 room: two columns at a quarter and three quarters of its length, two rows likewise
        assert len(xs) == 2 and len(ys) == 2
        assert abs(xs[0] - 1.5) < 0.1 and abs(xs[1] - 4.5) < 0.1 and abs(ys[0] - 1.0) < 0.1 and abs(ys[1] - 3.0) < 0.1
    # six of them: three columns, two rows
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": LIGHT, "room_ids": [ROOM], "count": 6, "where": "grid"})).json()
    assert len({p["x"] for p in r["places"]}) == 3 and len({p["y"] for p in r["places"]}) == 2


async def test_desks_with_chairs_in_one_call_and_a_virtual_anchor(client, tokens, world):
    boss = tokens.bearer("boss")
    r = await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "count": 2, "where": "along_wall", "companion_type_id": CHAIR})
    assert r.status_code == 200, r.text
    body = r.json()
    desks = [p for p in body["places"] if p["type_id"] == DESK]
    chairs = [p for p in body["places"] if p["type_id"] == CHAIR]
    assert body["companion"]["id"] == CHAIR and len(desks) == 2 and len(chairs) == 2
    for c in chairs:
        d = min(desks, key=lambda d: (d["x"] - c["x"]) ** 2 + (d["y"] - c["y"]) ** 2)
        assert ((d["x"] - c["x"]) ** 2 + (d["y"] - c["y"]) ** 2) ** 0.5 < 1.3 and abs((c["angle"] - d["angle"]) % 360 - 180) < 1
    # a chair before a desk that is only proposed: the anchor is given as a point
    r = await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": CHAIR, "count": 1, "where": "front_of",
                                                                    "anchor": {"type_id": DESK, "x": 3, "y": 3.5, "angle": 0}, "room_ids": [ROOM]})
    assert r.status_code == 200, r.text
    assert len(r.json()["places"]) == 1 and r.json()["places"][0]["angle"] == 180.0


async def test_a_wall_may_be_named(client, tokens, world):
    boss = tokens.bearer("boss")
    for side, test in (("west", lambda p: p["x"] < 0.6), ("north", lambda p: p["y"] > 3.4), ("east", lambda p: p["x"] > 5.4)):
        r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "count": 2, "where": "along_wall", "side": side})).json()
        assert r["rooms"][0]["placed"] == 2 and all(test(p) for p in r["places"]), (side, r["places"])


async def test_a_cabinet_stands_against_a_partition_as_against_a_wall(client, tokens, world):
    boss = tokens.bearer("boss")
    STORAGE = "cabinet-type"
    world.types[STORAGE] = {"id": STORAGE, "name": "Шкаф для документов", "category_id": "c", "price": None, "currency": "RUB", "size": [0.8, 0.4, 1.9]}
    for side in ("north", "east"):                       # the partition sides of the office
        r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": STORAGE, "room_ids": [ROOM], "count": 1, "where": "corners", "side": side})).json()
        assert r["rooms"][0]["placed"] == 1, (side, r["rooms"][0]["notes"])
    # but not through the partition or the door
    p = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": STORAGE, "room_ids": [ROOM], "count": 6, "where": "along_wall", "side": "north"})).json()["places"]
    assert all(3.4 < q["y"] < 4 for q in p)


async def test_a_place_on_a_named_wall_at_a_distance(client, tokens, world):
    boss = tokens.bearer("boss")
    # the office's south wall runs 0→6 along y=0 (counter-clockwise walk); 1 m from its start, the desk's back to the wall
    r = await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_wall", "side": "south", "along": 1.0})
    assert r.status_code == 200, r.text
    body = r.json()
    p = body["places"][0]
    assert body["rooms"][0]["notes"] == [] and abs(p["x"] - 1.7) < 0.02 and abs(p["y"] - 0.36) < 0.02 and p["angle"] == 180.0
    # the middle of the south wall is the door: the desk is slid aside and the shift is said
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_wall", "side": "south", "along": "middle"})).json()
    p, notes = r["places"][0], r["rooms"][0]["notes"]
    assert len(notes) == 1 and "мешает двери" in notes[0] and "сдвинуто" in notes[0]
    assert not (2.3 < p["x"] < 3.7) and abs(p["y"] - 0.36) < 0.02
    # two cabinets in a row from the end of the north wall
    STORAGE = "cabinet-type"
    world.types[STORAGE] = {"id": STORAGE, "name": "Шкаф", "category_id": "c", "price": None, "currency": "RUB", "size": [0.8, 0.4, 1.9]}
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": STORAGE, "room_ids": [ROOM], "count": 2, "where": "at_wall", "side": "north", "along": "end", "gap": 0})).json()
    xs = sorted(p["x"] for p in r["places"])
    assert len(xs) == 2 and all(abs(p["y"] - 3.79) < 0.02 for p in r["places"]) and abs(xs[0] - 0.4) < 0.02 and abs(xs[1] - 1.2) < 0.02
    # from the other corner: the south wall runs 0→6, so 1 m from its end puts the desk's right edge at x = 5
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_wall", "side": "south", "along": 1.0, "from_end": True})).json()
    assert abs(r["places"][0]["x"] - 4.3) < 0.02 and r["rooms"][0]["notes"] == []
    # too far along a 6 m wall (the north wall runs 6→0): pulled back to fit at the far corner, and said so
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_wall", "side": "north", "along": 5.5})).json()
    assert abs(r["places"][0]["x"] - 0.7) < 0.02 and "сдвинут" in r["rooms"][0]["notes"][0]
    # no such wall, no side
    assert (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_wall"})).status_code == 422


async def test_a_place_at_a_point_is_checked_and_moved_when_taken(client, tokens, world):
    boss = tokens.bearer("boss")
    ok = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_point", "anchor": {"x": 3, "y": 2, "angle": 90}})).json()
    assert ok["places"] == [{"floor_id": FLOOR, "room_id": ROOM, "type_id": DESK, "x": 3.0, "y": 2.0, "angle": 90.0}] and ok["rooms"][0]["notes"] == []
    # in the doorway: refused with the reason, and the nearest free place offered instead
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": DESK, "room_ids": [ROOM], "where": "at_point", "anchor": {"x": 3, "y": 0.5, "angle": 0}})).json()
    notes = r["rooms"][0]["notes"]
    assert len(r["places"]) == 1 and "мешает двери" in notes[0] and "ближайшее свободное место" in notes[0]
    p = r["places"][0]
    assert p["y"] > 0.5 and abs(p["x"] - 3) < 1.5
    # on another item: the reason names it
    world.put(DESK, "СТ-7", 1.5, 2.5)
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": CHAIR, "room_ids": [ROOM], "where": "at_point", "anchor": {"x": 1.5, "y": 2.5}})).json()
    assert "налезает на Рабочий стол СТ-7" in r["rooms"][0]["notes"][0]
    # a point outside the room: no room takes it
    r = (await client.post(f"{API}/placements", headers=boss, json={"building_id": BUILDING, "type_id": CHAIR, "floor_id": FLOOR, "where": "at_point", "anchor": {"x": 20, "y": 20}})).json()
    assert r["places"] == [] and r["rooms"] == []


async def test_layout_check_tells_what_is_wrong_and_where_to_put_it_instead(client, tokens, world):
    boss = tokens.bearer("boss")
    desk = world.put(DESK, "СТ-1", 3, 3.5)
    world.touch(desk["id"], angle=0)
    chair = world.put(CHAIR, "КР-1", 5, 2)
    SCREEN = "screen-type"
    world.types[SCREEN] = {"id": SCREEN, "name": "Экран", "category_id": "o", "price": None, "currency": "RUB", "size": [1.2, 0.1, 0.7], "elevation": 1.5, "wall_mounted": True, "values": {}}
    r = await client.post(f"{API}/layout-check", headers=boss, json={"building_id": BUILDING, "floor_id": FLOOR, "places": [
        {"type_id": CHAIR, "x": 3, "y": 2.8, "angle": 180},          # before the desk, facing it: fine
        {"type_id": CHAIR, "x": 3, "y": 0.4, "angle": 0},            # in the doorway
        {"type_id": DESK, "x": 3, "y": 3.5, "angle": 0},             # on the desk that stands there
        {"type_id": DESK, "x": 9, "y": 9, "angle": 0},               # outside any room
        {"type_id": SCREEN, "x": 0.06, "y": 2, "angle": 270},        # on the west wall, free: fine
        {"type_id": SCREEN, "x": 3, "y": 0.06, "angle": 180},        # over the door
        {"type_id": CHAIR, "x": 1, "y": 1, "angle": 0, "room_id": ROOM2},   # asked for the corridor, lands in the office
    ], "moves": [{"asset_id": chair["id"], "x": 5, "y": 2.5}]})
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert body["ok"] is False and body["problems"] == 5 and len(items) == 8
    assert items[0]["problems"] == [] and items[0]["faces"] == "Рабочий стол СТ-1" and items[0]["room"]["id"] == ROOM and items[0]["room"]["type"] == "office"
    assert items[1]["problems"] == ["мешает двери или проходу"] and items[1]["fix"] and not (2.3 < items[1]["fix"][0] < 3.7 and items[1]["fix"][1] < 0.8)
    assert items[2]["problems"] == ["налезает на Рабочий стол СТ-1"] and items[2]["fix"]
    assert items[3]["problems"] == ["вне помещений"] and items[3]["room"] is None and "fix" not in items[3]
    assert items[4]["problems"] == [] and items[4]["wall"].startswith("west 0.06")
    assert items[5]["problems"] == ["висит над дверью или окном"]
    assert items[6]["problems"][0].startswith("не в том помещении") and items[6]["room"]["id"] == ROOM
    # the moved chair is not in its own way at its new place
    assert items[7]["what"] == "Кресло посетителя КР-1" and items[7]["problems"] == []
    assert (await client.post(f"{API}/layout-check", headers=boss, json={"building_id": BUILDING, "floor_id": FLOOR})).status_code == 422
    assert (await client.post(f"{API}/layout-check", headers=tokens.bearer("clerk"), json={"building_id": BUILDING, "floor_id": FLOOR, "places": [{"type_id": DESK, "x": 1, "y": 1}]})).status_code in (403, 404)
