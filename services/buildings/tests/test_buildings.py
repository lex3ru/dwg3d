"""Buildings: requests, rights, invalid data, concurrent changes."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from twin_chassis.db import outbox

from .conftest import API, grant


async def events(app) -> list[dict]:
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        return [e for (e,) in rows]


async def test_create_list_change_delete(client, app, tokens, building):
    admin = tokens.admin()
    assert building["name"] == "Корпус А" and building["version"] == 1
    listed = (await client.get(f"{API}/buildings", headers=admin)).json()["items"]
    assert [(b["id"], b["floors"], b["rooms"], b["drawings"]) for b in listed] == [(building["id"], 0, 0, 0)]

    url = f"{API}/buildings/{building['id']}"
    r = await client.patch(url, json={"name": "Корпус Б", "version": 1}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "Корпус Б" and r.json()["version"] == 2
    # someone who still sees version 1 does not overwrite it
    stale = await client.patch(url, json={"name": "Корпус В", "version": 1}, headers=admin)
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert stale.json()["current"]["name"] == "Корпус Б"

    site = {"lat": 55.75, "lon": 37.62, "bearing": 30, "scale": 1, "tiles": None, "attribution": None}
    assert (await client.put(f"{API}/buildings/{building['id']}/site", json=site, headers=admin)).json()["site"] == site

    assert (await client.delete(f"{API}/buildings/{building['id']}", headers=admin)).status_code == 204
    assert (await client.get(f"{API}/buildings/{building['id']}", headers=admin)).status_code == 404
    assert (await client.get(f"{API}/buildings", headers=admin)).json()["items"] == []
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        types = [e["type"] for (e,) in rows]
    assert types == ["buildings.building.created", "buildings.building.changed", "buildings.building.changed",
                     "buildings.building.deleted"]


async def test_rights(client, tokens, building):
    url = f"{API}/buildings/{building['id']}"
    assert (await client.get(url)).status_code == 401
    assert (await client.post(f"{API}/buildings", json={"name": "x"})).status_code == 401

    # someone with no grant in the building: it does not exist for them
    user = tokens.bearer("user-1")
    assert (await client.get(url, headers=user)).status_code == 404
    assert (await client.get(f"{API}/buildings/{building['id']}/tree", headers=user)).status_code == 404
    assert (await client.patch(url, json={"name": "x", "version": 1}, headers=user)).status_code == 404
    assert (await client.get(f"{API}/buildings", headers=user)).json()["items"] == []
    assert (await client.post(f"{API}/buildings", json={"name": "x"}, headers=user)).status_code == 403

    service = tokens.bearer("svc", login="twin-svc-assets", service=True)       # other services read, do not change
    assert (await client.get(url, headers=service)).status_code == 200
    assert (await client.post(f"{API}/buildings", json={"name": "x"}, headers=service)).status_code == 403
    assert (await client.delete(url, headers=service)).status_code == 403


async def test_invalid_data(client, tokens, building):
    admin = tokens.admin()
    r = await client.post(f"{API}/buildings", json={"name": ""}, headers=admin)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "name"
    r = await client.put(f"{API}/buildings/{building['id']}/site", json={"lat": 95, "lon": 0}, headers=admin)
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "lat"
    assert (await client.get(f"{API}/buildings/not-an-id", headers=admin)).status_code == 422
    no_version = await client.patch(f"{API}/buildings/{building['id']}", json={"name": "x"}, headers=admin)
    assert no_version.status_code == 422


async def test_facade(client, tokens, building):
    admin, url = tokens.admin(), f"{API}/buildings/{building['id']}/facade"
    assert (await client.get(f"{url}.glb", headers=admin)).status_code == 404
    bad = await client.put(url, files={"file": ("f.glb", b"not a model")}, headers=admin)
    assert bad.status_code == 422

    glb = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 64
    r = await client.put(url, files={"file": ("Фасад.glb", glb)}, headers=admin)
    assert r.status_code == 200 and r.json()["facade"] == {"dx": 0, "dy": 0, "dz": 0, "rotation": 0, "scale": 1,
                                                           "name": "Фасад.glb", "size": len(glb)}
    assert (await client.get(f"{url}.glb", headers=admin)).content == glb
    aligned = await client.patch(url, json={"dx": 1.5, "rotation": 90, "scale": 0.001}, headers=admin)
    assert aligned.json()["facade"]["rotation"] == 90 and aligned.json()["facade"]["name"] == "Фасад.glb"
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(f"{url}.glb", headers=admin)).status_code == 404


async def test_pins(client, tokens, building):
    admin, url = tokens.admin(), f"{API}/buildings/{building['id']}/pins"
    created = await client.post(url, json={"pos": [1, 2, 3], "title": "Щиток", "note": "за дверью"}, headers=admin)
    pin = created.json()
    assert pin["pos"] == [1, 2, 3] and pin["created_by"] == "admin-1"
    assert [p["id"] for p in (await client.get(url, headers=admin)).json()["items"]] == [pin["id"]]

    moved = await client.patch(f"{API}/pins/{pin['id']}", json={"pos": [4, 5, 6], "version": 1}, headers=admin)
    assert moved.json()["pos"] == [4, 5, 6] and moved.json()["title"] == "Щиток"
    stale = await client.patch(f"{API}/pins/{pin['id']}", json={"title": "x", "version": 1}, headers=admin)
    assert stale.status_code == 409
    assert (await client.post(url, json={"pos": [1, 2]}, headers=admin)).status_code == 422
    assert (await client.post(url, json={"pos": [1, 2, 3]}, headers=tokens.bearer("user-1"))).status_code == 404

    assert (await client.delete(f"{API}/pins/{pin['id']}", headers=admin)).status_code == 204
    assert (await client.delete(f"{API}/pins/{pin['id']}", headers=admin)).status_code == 404


async def test_rights_by_area(client, tokens, importer, building, site):
    await site.build("base")
    admin = tokens.admin()
    other = (await client.post(f"{API}/buildings", json={"name": "Корпус Б"}, headers=admin)).json()
    floors = (await client.get(f"{API}/buildings/{building['id']}/tree", headers=admin)).json()["floors"]
    room = floors[0]["rooms"][0]
    url = f"{API}/buildings/{building['id']}"

    # a grant on one floor: the plan of the whole building is open, nothing can be changed
    viewer = grant(importer, "viewer", "viewer", "floor", floors[0]["id"], building["id"])
    assert [b["id"] for b in (await client.get(f"{API}/buildings", headers=viewer)).json()["items"]] == [building["id"]]
    for path in ("", "/tree", "/model", "/drawings", "/pins"):
        assert (await client.get(url + path, headers=viewer)).status_code == 200, path
    assert (await client.get(f"{API}/floors/{floors[1]['id']}/plan", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/rooms/{room['id']}", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/rooms", params={"building_id": building["id"]}, headers=viewer)).status_code == 200
    assert (await client.patch(url, json={"name": "x", "version": 1}, headers=viewer)).status_code == 403
    rename = {"name": "x", "version": room["version"]}
    assert (await client.patch(f"{API}/rooms/{room['id']}", json=rename, headers=viewer)).status_code == 403
    assert (await client.post(f"{url}/pins", json={"pos": [1, 2, 3]}, headers=viewer)).status_code == 403
    # another building is not there for them, even by a direct address
    assert (await client.get(f"{API}/buildings/{other['id']}", headers=viewer)).status_code == 404
    assert (await client.get(f"{API}/buildings/{other['id']}/tree", headers=viewer)).status_code == 404
    batch = await client.post(f"{API}/rooms/batch-get", json={"ids": [room["id"]]}, headers=tokens.bearer("nobody"))
    assert batch.json()["items"] == []

    # the administrator of the building changes it — but buildings are made and removed by the system administrator
    boss = grant(importer, "boss", "admin", "building", building["id"], building["id"])
    assert (await client.patch(f"{API}/rooms/{room['id']}", json=rename, headers=boss)).status_code == 200
    assert (await client.post(f"{url}/pins", json={"pos": [1, 2, 3]}, headers=boss)).status_code == 201
    assert (await client.put(f"{url}/site", json={"lat": 55, "lon": 37}, headers=boss)).status_code == 200
    assert (await client.delete(url, headers=boss)).status_code == 403
    assert (await client.post(f"{API}/buildings", json={"name": "x"}, headers=boss)).status_code == 403
    assert (await client.patch(f"{API}/buildings/{other['id']}", json={"name": "x", "version": 1},
                               headers=boss)).status_code == 404


async def test_access_service_away(client, app, tokens, importer, building):
    viewer = grant(importer, "viewer", "viewer", "building", building["id"], building["id"])
    boss = grant(importer, "boss", "admin", "building", building["id"], building["id"])
    url = f"{API}/buildings/{building['id']}"
    rights = app.state.rights

    def age(seconds: float) -> None:
        """What is known of anyone's scopes was learnt this long ago."""
        rights._known = {sub: (at - seconds, scopes) for sub, (at, scopes) in rights._known.items()}

    assert (await client.get(url, headers=viewer)).status_code == 200            # the scopes are known now
    assert (await client.get(url, headers=boss)).status_code == 200
    importer.access_up = False
    age(60)
    assert (await client.get(url, headers=viewer)).status_code == 200            # reading goes on by what was known
    down = await client.patch(url, json={"name": "x", "version": 1}, headers=boss)
    assert down.status_code == 503 and "изменения временно невозможны" in down.json()["detail"]
    assert (await client.get(url, headers=tokens.admin())).status_code == 200    # not asked about: the system admin
    age(600)
    assert (await client.get(url, headers=viewer)).status_code == 503            # too long ago to go by


async def test_comments_are_seen_by_those_who_see_the_target(client, app, tokens, importer, building, site):
    await site.build("base")
    admin, b = tokens.admin(), building["id"]
    tree = (await client.get(f"{API}/buildings/{b}/tree", headers=admin)).json()["floors"]
    floor, room = tree[0], tree[0]["rooms"][0]
    other = tree[1]["rooms"][0]
    asset = str(uuid4())
    importer.assets[asset] = {"id": asset, "building_id": b, "floor_id": floor["id"], "room_id": room["id"]}
    url = f"{API}/comments"
    keeper = grant(importer, "keeper", "responsible", "room", room["id"], b)
    viewer = grant(importer, "viewer", "viewer", "room", other["id"], b)

    # the keeper of a room comments on it, on an object in it and on a point of the floor
    on_room = await client.post(url, headers=keeper, json={"building_id": b, "target_kind": "room",
                                                      "target_id": room["id"], "body": "Течёт кран"})
    assert on_room.status_code == 201 and on_room.json()["author"]["name"] == "Иван Иванов"
    on_asset = await client.post(url, headers=keeper,
                                 json={"building_id": b, "target_kind": "asset", "target_id": asset, "body": "Шумит"})
    assert on_asset.status_code == 201 and on_asset.json()["room_id"] == room["id"]
    on_point = await client.post(url, headers=keeper, json={"building_id": b, "target_kind": "point",
                                                       "floor_id": floor["id"], "x": 1, "y": 2, "body": "Тут розетка"})
    assert on_point.status_code == 201
    bad = await client.post(url, headers=keeper,
                            json={"building_id": b, "target_kind": "point", "floor_id": floor["id"], "body": "x"})
    assert bad.status_code == 422
    gone = await client.post(url, headers=keeper,
                             json={"building_id": b, "target_kind": "asset", "target_id": str(uuid4()), "body": "x"})
    assert gone.status_code == 404

    # whoever sees the plan sees the point; the room's and the object's comments — only whoever sees the room
    mine = (await client.get(url, params={"building_id": b}, headers=keeper)).json()["items"]
    assert [c["target_kind"] for c in mine] == ["room", "asset", "point"]
    theirs = (await client.get(url, params={"building_id": b}, headers=viewer)).json()["items"]
    assert [c["target_kind"] for c in theirs] == ["point"]
    by_target = (await client.get(url, params={"building_id": b, "target_kind": "room", "target_id": room["id"]},
                                  headers=admin)).json()["items"]
    assert [c["body"] for c in by_target] == ["Течёт кран"]
    assert (await client.get(url, params={"building_id": str(uuid4())}, headers=viewer)).status_code == 404

    # closing: the author or the administrator; the viewer of another room does not even find it
    cid = on_room.json()["id"]
    assert (await client.post(f"{url}/{cid}/resolve", headers=viewer)).status_code == 404
    stranger = grant(importer, "stranger", "viewer", "room", room["id"], b)
    assert (await client.post(f"{url}/{cid}/resolve", headers=stranger)).status_code == 403
    assert (await client.patch(f"{url}/{cid}", json={"body": "x", "version": 1}, headers=stranger)).status_code == 403
    edited = await client.patch(f"{url}/{cid}", json={"body": "Течёт кран в углу", "version": 1}, headers=keeper)
    assert edited.status_code == 200 and edited.json()["version"] == 2
    assert (await client.patch(f"{url}/{cid}", json={"body": "y", "version": 1}, headers=keeper)).status_code == 409
    closed = await client.post(f"{url}/{cid}/resolve", headers=admin)
    assert closed.status_code == 200 and closed.json()["resolved_at"] and closed.json()["resolved_by"] == "admin-1"
    assert [c["id"] for c in (await client.get(url, params={"building_id": b}, headers=admin)).json()["items"]] != [cid]
    kept = (await client.get(url, params={"building_id": b, "resolved": "true"}, headers=admin)).json()["items"]
    assert cid in [c["id"] for c in kept]
    assert (await client.delete(f"{url}/{on_point.json()['id']}", headers=keeper)).status_code == 204
    types = [e["type"] for e in await events(app)]
    assert types.count("buildings.comment.created") == 3 and types.count("buildings.comment.resolved") == 1


async def test_a_guest_of_a_floor_sees_that_floor_only(client, app, tokens, building, site):
    await site.build("base")
    admin, b = tokens.admin(), building["id"]
    floors = (await client.get(f"{API}/buildings/{b}/tree", headers=admin)).json()["floors"]
    mine, other = floors[0], floors[1]
    guest = tokens.guest("floor", mine["id"], b, mine["id"])
    seen = (await client.get(f"{API}/buildings/{b}/tree", headers=guest)).json()["floors"]
    assert [f["id"] for f in seen] == [mine["id"]] and len(seen[0]["rooms"]) == 2
    assert (await client.get(f"{API}/floors/{mine['id']}/plan", headers=guest)).status_code == 200
    assert (await client.get(f"{API}/floors/{other['id']}/plan", headers=guest)).status_code == 404
    assert (await client.get(f"{API}/rooms/{other['rooms'][0]['id']}", headers=guest)).status_code == 404
    assert (await client.get(f"{API}/rooms/{mine['rooms'][0]['id']}", headers=guest)).status_code == 200
    rooms = (await client.get(f"{API}/rooms", params={"building_id": b}, headers=guest)).json()["items"]
    assert {r["floor_id"] for r in rooms} == {mine["id"]}
    model = (await client.get(f"{API}/buildings/{b}/model", headers=guest)).json()["drawings"][0]
    assert [f["floor_id"] for f in model["result"]["floors"]] == [mine["id"]]
    assert model["model_url"].endswith(f"model.glb?floor={mine['id']}")
    # no comments, no changes, nothing of another building
    assert (await client.get(f"{API}/comments", params={"building_id": b}, headers=guest)).json() == {"items": []}
    point = {"building_id": b, "target_kind": "point", "floor_id": mine["id"], "x": 1, "y": 1, "body": "x"}
    assert (await client.post(f"{API}/comments", json=point, headers=guest)).status_code == 403
    assert (await client.patch(f"{API}/rooms/{mine['rooms'][0]['id']}", json={"name": "x", "version": 1},
                               headers=guest)).status_code == 403
    assert (await client.get(f"{API}/buildings/{b}/revisions", headers=guest)).status_code == 403
    stranger = tokens.guest("floor", mine["id"], str(uuid4()), mine["id"])
    assert (await client.get(f"{API}/buildings/{b}/tree", headers=stranger)).status_code == 404
    # a guest of the whole building sees every floor
    whole = tokens.guest("building", b, b)
    assert len((await client.get(f"{API}/buildings/{b}/tree", headers=whole)).json()["floors"]) == 2
    whole_model = (await client.get(f"{API}/buildings/{b}/model", headers=whole)).json()["drawings"][0]
    assert "?floor=" not in whole_model["model_url"]
