"""A finished build of a drawing becomes floors and rooms that keep their ids."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from twin_chassis import Problem
from twin_chassis.db import inbox, outbox

from .conftest import API


async def events(app, type_: str | None = None) -> list[dict]:
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        return [e for (e,) in rows if type_ is None or e["type"] == type_]


async def tree(client, tokens, building) -> list[dict]:
    return (await client.get(f"{API}/buildings/{building['id']}/tree", headers=tokens.admin())).json()["floors"]


def room_ids(floors: list[dict]) -> dict[tuple[int, str, float], str]:
    return {(f["level"], r["name"], r["area"]): r["id"] for f in floors for r in f["rooms"]}


async def test_build_becomes_floors_and_rooms(client, app, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")

    floors = await tree(client, tokens, building)
    assert [(f["level"], len(f["rooms"])) for f in floors] == [(1, 2), (2, 2)]
    assert {(r["name"], r["area"]) for r in floors[0]["rooms"]} == {("", 34.78), ("Кабинет", 48.69)}
    assert next(r["type"] for r in floors[0]["rooms"] if r["name"] == "Кабинет") == "office"
    listed = (await client.get(f"{API}/buildings", headers=admin)).json()["items"][0]
    assert (listed["floors"], listed["rooms"], listed["drawings"]) == (2, 4, 1)

    # the model: where the file is, and which node is which floor and room
    model = (await client.get(f"{API}/buildings/{building['id']}/model", headers=admin)).json()["drawings"]
    assert len(model) == 1 and model[0]["id"] == site.drawing_id
    assert model[0]["model_url"] == f"/api/import/v1/builds/{model[0]['build_id']}/files/model.glb"
    assert model[0]["placement"] == {"dx": 0, "dy": 0, "dz": 0, "rotation": 0}
    by_level = {f["level"]: f for f in model[0]["result"]["floors"]}
    assert by_level[1]["floor_id"] == floors[0]["id"] and by_level[1]["node"] == f"floor_{by_level[1]['id']}"
    assert {m["id"] for m in by_level[1]["rooms"]} == {r["id"] for r in floors[0]["rooms"]}

    # the plan of a floor carries the same room ids
    plan = (await client.get(f"{API}/floors/{floors[0]['id']}/plan", headers=admin)).json()
    assert {r["id"] for r in plan["plan"]["rooms"]} == {r["id"] for r in floors[0]["rooms"]}
    assert plan["plan"]["walls"] and plan["floor"]["candidate"] == by_level[1]["id"]

    published = await events(app, "buildings.revision.published")
    assert len(published) == 1 and published[0]["building_id"] == building["id"]
    assert len(published[0]["data"]["rooms"]["created"]) == 4 and published[0]["data"]["rooms"]["retired"] == []


async def test_search_and_locate(client, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")
    floors = await tree(client, tokens, building)
    office = next(r for r in floors[0]["rooms"] if r["name"] == "Кабинет")

    found = (await client.get(f"{API}/rooms", params={"building_id": building["id"], "q": "каб"}, headers=admin)).json()
    assert len(found["items"]) == 2 and {r["name"] for r in found["items"]} == {"Кабинет"}
    one = await client.get(f"{API}/rooms", params={"building_id": building["id"], "floor_id": floors[0]["id"],
                                                  "type": "office"}, headers=admin)
    assert [r["id"] for r in one.json()["items"]] == [office["id"]]
    assert (await client.get(f"{API}/rooms", params={"building_id": building["id"], "q": "100%"},
                             headers=admin)).json()["items"] == []

    full = (await client.get(f"{API}/rooms/{office['id']}", headers=admin)).json()
    assert full["polygon"] and full["floor_id"] == floors[0]["id"]
    batch = await client.post(f"{API}/rooms/batch-get", json={"ids": [office["id"], building["id"]]}, headers=admin)
    assert [r["id"] for r in batch.json()["items"]] == [office["id"]]

    # which room a point is in: inside the office, in the other room, outside the building
    r = await client.post(f"{API}/floors/{floors[0]['id']}/locate",
                          json={"points": [[8.4, 4.0], [2.0, 4.0], [50.0, 50.0]]}, headers=admin)
    other = next(x for x in floors[0]["rooms"] if x["id"] != office["id"])
    assert r.json()["rooms"] == [office["id"], other["id"], None]
    assert (await client.post(f"{API}/floors/{floors[0]['id']}/locate", json={"points": [[1]]},
                              headers=admin)).status_code == 422


async def test_rebuild_keeps_every_id(client, app, tokens, building, site):
    await site.build("base")
    before = await tree(client, tokens, building)
    await site.build("base")                         # the same drawing built again
    after = await tree(client, tokens, building)

    assert [f["id"] for f in after] == [f["id"] for f in before]
    assert room_ids(after) == room_ids(before)
    second = (await events(app, "buildings.revision.published"))[1]["data"]
    assert second["rooms"] == {"created": [], "changed": [], "retired": []}
    assert second["floors"]["created"] == [] and len(second["floors"]["active"]) == 2


async def test_changed_floor_keeps_untouched_rooms(client, app, tokens, building, site):
    await site.build("base")
    before = room_ids(await tree(client, tokens, building))

    await site.build("split")                        # a wall added on floor 1 splits the office in two
    floors = await tree(client, tokens, building)
    after = room_ids(floors)
    assert len(floors[0]["rooms"]) == 3 and len(floors[1]["rooms"]) == 2
    # floor 2 was not touched; on floor 1 the other room is the same room
    assert after[(2, "Кабинет", 48.69)] == before[(2, "Кабинет", 48.69)]
    assert after[(2, "", 34.78)] == before[(2, "", 34.78)]
    assert after[(1, "", 34.78)] == before[(1, "", 34.78)]
    # the office continues in its larger part, the smaller part is a new room
    assert after[(1, "Кабинет", 30.6)] == before[(1, "Кабинет", 48.69)]
    assert after[(1, "", 17.44)] not in before.values()
    change = (await events(app, "buildings.revision.published"))[-1]["data"]["rooms"]
    assert change["created"] == [after[(1, "", 17.44)]] and change["retired"] == []
    assert change["changed"] == [{"id": after[(1, "Кабинет", 30.6)], "outline": True}]

    await site.build("base")                         # the wall is removed again: the new room is gone
    floors = await tree(client, tokens, building)
    assert room_ids(floors) == before
    retired = await events(app, "buildings.room.retired")
    assert [e["data"]["room_id"] for e in retired] == [after[(1, "", 17.44)]]
    assert retired[0]["room_id"] == after[(1, "", 17.44)] and retired[0]["floor_id"] == floors[0]["id"]
    # retired, not deleted: whoever refers to it can still read it
    gone = (await client.get(f"{API}/rooms/{after[(1, '', 17.44)]}", headers=tokens.admin())).json()
    assert gone["status"] == "retired"
    all_rooms = await client.get(f"{API}/rooms", params={"building_id": building["id"], "status": "all"},
                                 headers=tokens.admin())
    assert len(all_rooms.json()["items"]) == 5


async def test_name_given_by_hand_survives_a_rebuild(client, app, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")
    floors = await tree(client, tokens, building)
    room = next(r for r in floors[0]["rooms"] if r["name"] == "")

    r = await client.patch(f"{API}/rooms/{room['id']}", json={"name": "Процедурная", "type": "medical",
                                                             "version": room["version"]}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "Процедурная"
    stale = await client.patch(f"{API}/rooms/{room['id']}", json={"name": "x", "version": room["version"]},
                               headers=admin)
    assert stale.status_code == 409
    renamed = await client.patch(f"{API}/floors/{floors[0]['id']}",
                                 json={"name": "Первый", "version": floors[0]["version"]}, headers=admin)
    assert renamed.status_code == 200

    await site.build("base")
    floors = await tree(client, tokens, building)
    again = next(r for r in floors[0]["rooms"] if r["id"] == room["id"])
    assert (again["name"], again["type"]) == ("Процедурная", "medical") and floors[0]["name"] == "Первый"
    # and the model shows the names given by hand
    model = (await client.get(f"{API}/buildings/{building['id']}/model", headers=admin)).json()["drawings"][0]["result"]
    floor = next(f for f in model["floors"] if f["floor_id"] == floors[0]["id"])
    assert floor["name"] == "Первый"
    assert next(m for m in floor["rooms"] if m["id"] == room["id"])["name"] == "Процедурная"
    changed = await events(app, "buildings.room.changed")
    assert changed[0]["data"] == {"room_id": room["id"], "fields": ["name", "type"]}


async def test_events_out_of_order_and_twice(client, app, tokens, building, site):
    first = site.finished("split", n=1)
    second = site.finished("base", n=2)
    assert await app.state.bus.handle("build-finished", second) is True
    assert await app.state.bus.handle("build-finished", first) is True      # late: handled, changes nothing
    assert await app.state.bus.handle("build-finished", second) is False     # delivered again
    floors = await tree(client, tokens, building)
    assert [len(f["rooms"]) for f in floors] == [2, 2]
    assert len(await events(app, "buildings.revision.published")) == 1


async def test_import_down_leaves_the_event_for_later(client, app, tokens, building, site, importer):
    event = site.finished("base")
    importer.up = False
    with pytest.raises(Problem) as failure:
        await app.state.bus.handle("build-finished", event)
    assert failure.value.status == 503
    async with app.state.db.begin() as session:                              # not marked as handled
        handled = (await session.execute(select(inbox.c.handler).where(inbox.c.handler == "build-finished"))).all()
    assert handled == []
    assert await tree(client, tokens, building) == []

    importer.up = True
    assert await app.state.bus.handle("build-finished", event) is True       # redelivered
    assert len(await tree(client, tokens, building)) == 2


async def test_event_about_an_unknown_building_is_ignored(app, importer, site):
    from uuid import uuid4

    stranger = type(site)(app, importer, str(uuid4()))
    await stranger.upload()
    await stranger.build("base")
    assert importer.calls == [] and await events(app, "buildings.revision.published") == []


async def test_deleted_drawing_retires_its_floors_and_rooms(client, app, tokens, building, site):
    await site.build("base")
    await site.delete()
    assert await tree(client, tokens, building) == []
    empty = await client.get(f"{API}/buildings/{building['id']}/model", headers=tokens.admin())
    assert empty.json()["drawings"] == []
    assert len(await events(app, "buildings.room.retired")) == 4


async def test_placement_of_a_drawing(client, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")
    url = f"{API}/buildings/{building['id']}/drawings"
    drawing = (await client.get(url, headers=admin)).json()["items"][0]
    assert drawing["name"] == "Корпус А.dxf" and drawing["build_n"] == 1

    r = await client.patch(f"{url}/{drawing['id']}", json={"placement": {"dx": 40, "dy": -5, "rotation": 90},
                                                          "version": drawing["version"]}, headers=admin)
    assert r.status_code == 200 and r.json()["placement"] == {"dx": 40, "dy": -5, "dz": 0, "rotation": 90}
    await site.build("base")                         # a rebuild does not move the drawing back
    model = (await client.get(f"{API}/buildings/{building['id']}/model", headers=admin)).json()["drawings"][0]
    assert model["placement"]["dx"] == 40
    bad = await client.patch(f"{url}/{drawing['id']}", json={"placement": {"rotation": 1000}, "version": 9},
                             headers=admin)
    assert bad.status_code == 422
