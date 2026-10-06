"""People in rooms: who assigns, who sees whom."""
from __future__ import annotations

from uuid import uuid4

from twin_chassis.events import envelope

from .conftest import API, BUILDING, DESK, FLOOR, ROOM_A, ROOM_B  # noqa: F401
from .test_people import add, events


async def test_assigning_and_seeing_people_by_rooms(client, app, tokens, access):
    boss = tokens.bearer("boss")
    anna = await add(client, boss, full_name="Петрова Анна", email="anna@example.test", phone="100")
    ivan = await add(client, boss, full_name="Иванов Иван")
    url = f"{API}/people/{anna['id']}/assignments/{ROOM_A}"
    # the administrator of the building assigns, with a workplace that must be in the room
    bad = await client.put(url, json={"workplace_asset_id": str(uuid4())}, headers=boss)
    assert bad.status_code == 422
    a = await client.put(url, json={"workplace_asset_id": DESK}, headers=boss)
    assert a.status_code == 200 and a.json()["building_id"] == BUILDING and a.json()["floor_id"] == FLOOR
    again = await client.put(url, json={"workplace_asset_id": DESK}, headers=boss)
    assert again.status_code == 200
    ivans = f"{API}/people/{ivan['id']}/assignments"
    assert (await client.put(f"{ivans}/{ROOM_B}", json={}, headers=boss)).status_code == 200
    assert (await client.put(f"{ivans}/{uuid4()}", json={}, headers=boss)).status_code == 404
    assigned = [e for e in await events(app) if e["type"] == "people.person.assigned"]
    assert len(assigned) == 2 and assigned[0]["room_id"] == ROOM_A and assigned[0]["data"]["workplace_asset_id"] == DESK

    # a colleague who sees room A: Anna with her contacts, not Ivan; the keeper sees everyone
    mate = access.person("mate", str(uuid4()), ("viewer", "room", ROOM_A))
    room = (await client.get(f"{API}/rooms/{ROOM_A}/people", headers=mate)).json()["items"]
    assert [(p["full_name"], p["phone"], p["workplace_asset_id"]) for p in room] == [("Петрова Анна", "100", DESK)]
    assert (await client.get(f"{API}/rooms/{ROOM_B}/people", headers=mate)).status_code == 404     # not theirs to see
    listed = (await client.get(f"{API}/people", params={"building_id": BUILDING}, headers=mate)).json()["items"]
    assert [p["full_name"] for p in listed] == ["Петрова Анна"]
    assert (await client.get(f"{API}/people", headers=mate)).status_code == 403
    assert (await client.get(f"{API}/people/{anna['id']}", headers=mate)).json()["email"] == "anna@example.test"
    assert (await client.get(f"{API}/people/{ivan['id']}", headers=mate)).status_code == 404
    mine = (await client.get(f"{API}/people/{anna['id']}/assignments", headers=mate)).json()["items"]
    assert [x["room_id"] for x in mine] == [ROOM_A]
    everyone = (await client.get(f"{API}/people", params={"building_id": BUILDING}, headers=boss)).json()["items"]
    assert len(everyone) == 2
    # the administrator of another building keeps the directory, but who sits where here is not theirs to know
    other = access.person("other-boss", str(uuid4()), ("admin", "building", str(uuid4())))
    assert len((await client.get(f"{API}/people", headers=other)).json()["items"]) == 2
    assert (await client.get(f"{API}/people", params={"building_id": BUILDING}, headers=other)).json()["items"] == []
    assert (await client.get(f"{API}/people", params={"room_id": ROOM_A}, headers=other)).json()["items"] == []
    assert (await client.get(f"{API}/people/{anna['id']}/assignments", headers=other)).json()["items"] == []
    # a person sees their own record and assignments without any right on a room
    me = access.person("kc-ivan", ivan["id"])
    assert (await client.get(f"{API}/people/{ivan['id']}", headers=me)).status_code == 200
    assert (await client.get(f"{ivans}", headers=me)).json()["items"][0]["room_id"] == ROOM_B
    # whoever only looks does not assign or unassign; a stranger gets 404 from the buildings service
    assert (await client.put(url, json={}, headers=mate)).status_code == 403
    assert (await client.delete(url, headers=mate)).status_code == 403
    annas = f"{API}/people/{anna['id']}/assignments"
    assert (await client.put(f"{annas}/{ROOM_B}", json={}, headers=mate)).status_code == 403
    assert (await client.delete(url, headers=boss)).status_code == 204
    assert (await client.delete(url, headers=boss)).status_code == 404
    assert (await client.get(f"{API}/rooms/{ROOM_A}/people", headers=mate)).json()["items"] == []
    unassigned = [e for e in await events(app) if e["type"] == "people.person.unassigned"]
    assert [e["person_id"] for e in unassigned] == [anna["id"]]
    # the reconciliation of rights asks for every assignment, with a service token
    svc = tokens.bearer("svc", service=True, login="twin-svc-access")
    every = (await client.get(f"{API}/assignments", headers=svc)).json()["items"]
    assert [x["person_id"] for x in every] == [ivan["id"]]
    assert (await client.get(f"{API}/assignments", headers=boss)).status_code == 403


async def test_rooms_and_workplaces_that_are_no_more(client, app, tokens):
    boss = tokens.bearer("boss")
    anna = await add(client, boss, full_name="Петрова Анна")
    await client.put(f"{API}/people/{anna['id']}/assignments/{ROOM_A}", json={"workplace_asset_id": DESK}, headers=boss)
    await client.put(f"{API}/people/{anna['id']}/assignments/{ROOM_B}", json={}, headers=boss)
    retired = envelope("assets.asset.retired", ("asset", DESK), {"asset_id": DESK, "from": "in_use", "to": "retired"},
                       actor={"kind": "user", "id": "boss"}, building_id=BUILDING, asset_id=DESK)
    assert await app.state.bus.handle("asset-retired", retired) is True
    rooms = (await client.get(f"{API}/people/{anna['id']}/assignments", headers=boss)).json()["items"]
    assert [(x["room_id"], x["workplace_asset_id"]) for x in rooms] == [(ROOM_A, None), (ROOM_B, None)]
    gone = envelope("buildings.room.retired", ("room", ROOM_A), {"room_id": ROOM_A, "floor_id": FLOOR},
                    actor={"kind": "service", "id": "buildings"}, building_id=BUILDING, floor_id=FLOOR, room_id=ROOM_A)
    assert await app.state.bus.handle("room-retired", gone) is True
    rooms = (await client.get(f"{API}/people/{anna['id']}/assignments", headers=boss)).json()["items"]
    assert [x["room_id"] for x in rooms] == [ROOM_B]
    assert [e["type"] for e in await events(app)][-1] == "people.person.unassigned"


async def test_people_of_merged_rooms_work_in_the_heir(client, app, tokens):
    boss = tokens.bearer("boss")
    anna = await add(client, boss, full_name="Петрова Анна")
    ivan = await add(client, boss, full_name="Иванов Иван")
    await client.put(f"{API}/people/{anna['id']}/assignments/{ROOM_B}", json={}, headers=boss)
    await client.put(f"{API}/people/{ivan['id']}/assignments/{ROOM_A}", json={}, headers=boss)
    await client.put(f"{API}/people/{ivan['id']}/assignments/{ROOM_B}", json={}, headers=boss)
    merged = envelope("buildings.room.merged", ("room", ROOM_A), {"from": [ROOM_B], "into": ROOM_A, "floor_id": FLOOR},
                      actor={"kind": "user", "id": "boss"}, building_id=BUILDING, floor_id=FLOOR, room_id=ROOM_A)
    assert await app.state.bus.handle("room-merged", merged) is True
    for person in (anna, ivan):
        rooms = (await client.get(f"{API}/people/{person['id']}/assignments", headers=boss)).json()["items"]
        assert [x["room_id"] for x in rooms] == [ROOM_A]
