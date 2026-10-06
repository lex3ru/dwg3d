"""A variant is made, edited as in the editor, compared with the fact, priced, applied — partly when the fact
changed under it; a stale one is marked."""
from __future__ import annotations

from twin_chassis.events import envelope

from .conftest import API, BUILDING, CHAIR, DESK, FLOOR


async def test_a_variant_from_making_to_applying(client, app, tokens, world):
    boss = tokens.bearer("boss")
    desk = world.put(DESK, "СТ-0001", x=1.0)
    chair = world.put(CHAIR, "КР-0001", x=2.0)
    old = world.put(CHAIR, "КР-0002", x=3.0)
    made = await client.post(f"{API}/variants", json={"building_id": BUILDING, "name": "Перестановка"}, headers=boss)
    assert made.status_code == 201
    v = made.json()
    url = f"{API}/variants/{v['id']}"
    assert (await client.post(f"{API}/variants", json={"building_id": BUILDING, "name": "x"},
                              headers=tokens.bearer("clerk"))).status_code == 404

    # as in the editor: the desk moved, the old chair taken out, two new chairs, a note
    edits = [{"kind": "move", "asset_id": desk["id"], "version": 1, "floor_id": FLOOR, "x": 5.0, "y": 2.0, "angle": 90},
             {"kind": "remove", "asset_id": old["id"], "version": 1},
             {"kind": "place", "type_id": CHAIR, "floor_id": FLOOR, "x": 6.0, "y": 1.0, "inventory_no": "КР-0010"},
             {"kind": "place", "type_id": CHAIR, "floor_id": FLOOR, "x": 7.0, "y": 1.0},
             {"kind": "note", "asset_id": chair["id"], "version": 1, "note": "к окну"}]
    r = await client.post(f"{url}/edits", json={"edits": edits}, headers=boss)
    assert r.status_code == 200
    new_op = r.json()["results"][3]["op_id"]
    # moving the desk again keeps one operation; the new chair moved is its own operation edited
    again = [{"kind": "move", "asset_id": desk["id"], "version": 1, "floor_id": FLOOR, "x": 5.5, "y": 2.0, "angle": 90},
             {"kind": "move", "op_id": new_op, "floor_id": FLOOR, "x": 7.5, "y": 1.0}]
    assert (await client.post(f"{url}/edits", json={"edits": again}, headers=boss)).status_code == 200
    got = (await client.get(url, headers=boss)).json()
    assert got["counts"] == {"add": 2, "move": 1, "change": 1, "remove": 1} and not got["stale"]

    # the view: the fact with the variant on it
    items = {o["key"]: o for o in (await client.get(f"{url}/view", headers=boss)).json()["items"]}
    assert items[f"asset:{desk['id']}"]["x"] == 5.5 and items[f"asset:{desk['id']}"]["change"] == "moved"
    assert items[f"asset:{old['id']}"]["removed"] is True
    assert items[f"new:{new_op}"]["x"] == 7.5 and items[f"new:{new_op}"]["inventory_no"] is None

    # compared with the fact: what and how much, with prices
    cmp = (await client.get(f"{API}/compare", params={"building_id": BUILDING, "a": "fact", "b": v["id"]}, headers=boss)).json()
    assert cmp["counts"] == {"added": 2, "removed": 1, "moved": 1, "changed": 1, "same": 0}
    rows = {i["name"]: i for i in cmp["items"]}
    assert (rows["Кресло посетителя"]["qty_a"], rows["Кресло посетителя"]["qty_b"]) == (2, 3)
    assert rows["Кресло посетителя"]["sum_b"] == 10500.0 and cmp["totals"]["RUB"]["delta"] == 3500.0
    moved = next(o for o in cmp["objects"] if o["change"] == "moved")
    assert moved["what"] == ["место", "поворот"] and moved["from"]["at"] == [1.0, 1.0]
    spec = (await client.get(f"{url}/spec", headers=boss)).json()
    assert spec["totals"]["RUB"] == {"a": 19000.0, "b": 22500.0, "delta": 3500.0}

    # meanwhile the desk is moved in the fact: the variant is stale (the event says so), its move conflicts
    world.touch(desk["id"], x=1.2)
    event = envelope("assets.asset.moved", ("asset", desk["id"]), {"asset_id": desk["id"], "from_room_id": "r", "to_room_id": "r",
                                                                    "from_building_id": BUILDING},
                     actor={"kind": "user", "id": "other"}, building_id=BUILDING, asset_id=desk["id"])
    assert await app.state.bus.handle("asset-changed", event) is True
    listed = (await client.get(f"{API}/variants", params={"building_id": BUILDING}, headers=boss)).json()["items"]
    assert listed[0]["stale"] is True and listed[0]["stale_reasons"][0]["what"] == "перемещён"
    got = (await client.get(url, headers=boss)).json()
    assert [o["conflict"] for o in got["ops"] if o["op"] == "move"] == ["changed"]

    # applied: what conflicts or lacks a number is refused and stays; the rest is done, in the objects
    applied = await client.post(f"{url}/apply", headers=boss)
    assert applied.status_code == 200
    result = applied.json()["result"]
    assert sorted(x["op"] for x in result["applied"]) == ["add", "change", "remove"]
    assert sorted((x["op"], x["reason"]) for x in result["refused"]) == [
        ("add", "нет инвентарного номера"), ("move", "объект изменён после того, как вариант был составлен")]
    assert applied.json()["status"] == "draft" and applied.json()["counts"] == {"add": 1, "move": 1, "change": 0, "remove": 0}
    assert world.assets[old["id"]]["state"] == "retired" and world.assets[chair["id"]]["note"] == "к окну"
    assert any(a["inventory_no"] == "КР-0010" for a in world.assets.values())

    # the rest corrected: the desk's place taken anew, a number given — applied in full
    fix = [{"kind": "move", "asset_id": desk["id"], "version": world.assets[desk["id"]]["version"], "floor_id": FLOOR,
            "x": 5.5, "y": 2.0, "angle": 90},
           {"kind": "move", "op_id": new_op, "inventory_no": "КР-0011", "floor_id": FLOOR, "x": 7.5, "y": 1.0}]
    assert (await client.post(f"{url}/edits", json={"edits": fix}, headers=boss)).status_code == 200
    final = (await client.post(f"{url}/apply", headers=boss)).json()
    assert final["status"] == "applied" and final["result"]["refused"] == [] and final["counts"]["move"] == 0
    assert world.assets[desk["id"]]["x"] == 5.5
    assert (await client.post(f"{url}/edits", json={"edits": fix}, headers=boss)).status_code == 409


async def test_copy_rename_delete(client, tokens, world):
    boss = tokens.bearer("boss")
    desk = world.put(DESK, "СТ-0001", x=1.0)
    v = (await client.post(f"{API}/variants", json={"building_id": BUILDING, "name": "А"}, headers=boss)).json()
    await client.post(f"{API}/variants/{v['id']}/edits", headers=boss,
                      json={"edits": [{"kind": "remove", "asset_id": desk["id"], "version": 1}]})
    copy = (await client.post(f"{API}/variants", json={"building_id": BUILDING, "name": "Б", "based_on": v["id"]},
                              headers=boss)).json()
    assert copy["based_on"] == v["id"] and copy["counts"]["remove"] == 1
    cmp = (await client.get(f"{API}/compare", params={"building_id": BUILDING, "a": v["id"], "b": copy["id"]}, headers=boss)).json()
    assert cmp["counts"]["same"] == 0 and cmp["objects"] == []
    renamed = await client.patch(f"{API}/variants/{copy['id']}", json={"name": "Б-2", "version": copy["version"]}, headers=boss)
    assert renamed.json()["name"] == "Б-2"
    assert (await client.delete(f"{API}/variants/{v['id']}", headers=boss)).status_code == 204
    assert [x["name"] for x in (await client.get(f"{API}/variants", params={"building_id": BUILDING},
                                                  headers=boss)).json()["items"]] == ["Б-2"]


async def test_a_guest_by_a_link_has_no_variants(client, app, tokens, world):
    boss = tokens.bearer("boss")
    world.put(DESK, "СТ-0001", x=1.0)
    v = (await client.post(f"{API}/variants", json={"building_id": BUILDING, "name": "Перестановка"}, headers=boss)).json()
    guest = tokens.guest("building", BUILDING, BUILDING)
    # every request, about this very variant and building, is refused before anything is looked at
    asks = [(method.upper(), path.replace("{variant_id}", v["id"]))
            for path, methods in app.openapi()["paths"].items() for method in methods]
    assert len(asks) >= 10
    for method, path in asks:
        r = await client.request(method, path, params={"building_id": BUILDING, "a": v["id"], "b": "fact"},
                                 headers=guest)
        assert (r.status_code, r.json()["code"]) == (403, "guest"), (method, path, r.text)
    # the variant is as it was
    assert (await client.get(f"{API}/variants/{v['id']}", headers=boss)).json()["name"] == "Перестановка"
