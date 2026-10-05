"""Buildings: requests, rights, invalid data, concurrent changes."""
from __future__ import annotations

from sqlalchemy import select
from twin_chassis.db import outbox

from .conftest import API, grant


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
