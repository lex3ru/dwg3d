"""Objects on the plan: placing, properties by rights, state, moving, history, files."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from twin_chassis.db import outbox
from twin_chassis.events import envelope

from .conftest import API, BUILDING, FLOOR, FLOOR_2, ROOM_A, ROOM_B, ROOM_C, kind, prop, put


async def events(app, type_: str | None = None) -> list[dict]:
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        return [e for (e,) in rows if type_ is None or e["type"] == type_]


async def get(client, headers, asset: dict) -> dict:
    return (await client.get(f"{API}/assets/{asset['id']}", headers=headers)).json()


async def test_placing(client, app, world, boss):
    a = await put(client, boss, world, "scope", "М-0001", x=2.0)
    assert (a["room_id"], a["building_id"], a["type_name"], a["state"]) == (ROOM_A, BUILDING, "Гастроскоп", "in_use")
    assert len(a["qr_code"]) == 10 and a["needs_fill"] is False
    created = (await events(app))[-1]
    assert created["type"] == "assets.asset.created" and (created["room_id"], created["asset_id"]) == (ROOM_A, a["id"])

    body = {"type_id": world.types["couch"]["id"], "floor_id": FLOOR, "x": 2, "y": 2, "inventory_no": "М-0002"}
    outside = await client.post(f"{API}/assets", json={**body, "x": 50}, headers=boss)
    assert outside.status_code == 422 and outside.json()["code"] == "outside"
    taken = await client.post(f"{API}/assets", json={**body, "inventory_no": "М-0001"}, headers=boss)
    assert taken.status_code == 409 and taken.json()["code"] == "inventory_no_taken"
    assert (await client.post(f"{API}/assets", json={**body, "type_id": str(uuid4())}, headers=boss)).status_code == 422
    assert (await client.post(f"{API}/assets", json={**body, "props": {"wear": "awful"}}, headers=boss)).status_code == 422
    assert (await client.post(f"{API}/assets", json=body)).status_code == 401
    # who only looks does not place; to a stranger the place does not exist
    viewer = world.person("viewer", ("viewer", "room", ROOM_A))
    assert (await client.post(f"{API}/assets", json=body, headers=viewer)).status_code == 403
    assert (await client.post(f"{API}/assets", json=body, headers=world.person("stranger"))).status_code == 404

    # the number of a retired object is not used again
    retired = await client.post(f"{API}/assets/{a['id']}/state", json={"state": "retired", "version": 1}, headers=boss)
    assert retired.json()["state"] == "retired"
    again = await client.post(f"{API}/assets", json={**body, "inventory_no": "М-0001"}, headers=boss)
    assert again.status_code == 409


async def test_on_the_plan_without_a_number_and_on_the_books_later(client, app, world, boss):
    """A thing stands on the plan with no inventory number; it is put on the books by giving it one (its own or the
    next free), and from then on it is only written off. One not on the books is deleted, not written off."""
    chair = await put(client, boss, world, "couch", None, x=2)
    assert chair["inventory_no"] is None and chair["state"] == "in_use"
    created = (await events(app, "assets.asset.created"))[-1]
    assert "inventory_no" not in created["data"]
    url = f"{API}/assets/{chair['id']}"
    # a second one without a number: no clash of numbers between them
    other = await put(client, boss, world, "couch", None, x=3)
    numbered = await put(client, boss, world, "couch", "КШ-0007", x=6)

    # the lists tell them apart; the search survives the missing number
    async def ids(**params) -> list[str]:
        return [a["id"] for a in (await client.get(f"{API}/assets", params=params, headers=boss)).json()["items"]]
    assert await ids(accounted=False) == [chair["id"], other["id"]] and await ids(accounted=True) == [numbered["id"]]
    assert await ids(q="куш") == [numbered["id"], chair["id"], other["id"]]       # a number sorts before none
    # the label works without a number; the number cannot be set past the registering
    assert (await client.get(f"{url}/label", headers=boss)).headers["content-type"] == "application/pdf"
    assert (await client.patch(url, json={"inventory_no": "КШ-0001", "version": 1}, headers=boss)).json()["code"] == "not_accounted"
    # writing off is for what is on the books
    assert (await client.post(f"{url}/state", json={"state": "retired", "version": 1}, headers=boss)).json()["code"] == "not_accounted"
    assert (await client.post(f"{url}/state", json={"state": "faulty", "version": 1}, headers=boss)).json()["state"] == "faulty"

    # on the books: the next free number of the type, or one's own
    keeper = world.person("keeper", ("responsible", "asset", chair["id"]))
    assert (await client.post(f"{url}/register", json={"version": 2}, headers=keeper)).status_code == 403
    r = await client.post(f"{url}/register", json={"version": 2}, headers=boss)
    assert r.status_code == 200 and r.json()["inventory_no"] == "КШ-0008" and r.json()["version"] == 3
    registered = (await events(app, "assets.asset.registered"))[-1]
    assert registered["data"] == {"asset_id": chair["id"], "type_id": chair["type_id"], "inventory_no": "КШ-0008"}
    assert (await client.post(f"{url}/register", json={"version": 3}, headers=boss)).json()["code"] == "accounted"
    taken = await client.post(f"{API}/assets/{other['id']}/register", json={"inventory_no": "КШ-0008", "version": 1}, headers=boss)
    assert taken.status_code == 409 and taken.json()["code"] == "inventory_no_taken"
    mine = await client.post(f"{API}/assets/{other['id']}/register", json={"inventory_no": " КШ-0100 ", "version": 1}, headers=boss)
    assert mine.json()["inventory_no"] == "КШ-0100"
    assert [h["action"] for h in (await client.get(f"{url}/history", headers=boss)).json()["items"]] == ["registered", "state", "created"]
    # the number cannot be taken away: off the books is written off
    assert (await client.patch(url, json={"inventory_no": None, "version": 3}, headers=boss)).status_code == 422
    assert (await client.patch(url, json={"inventory_no": " ", "version": 3}, headers=boss)).status_code == 422

    # deleting: only what is not on the books, only by the administrator; gone with its files
    assert (await client.delete(url, headers=boss)).json()["code"] == "accounted"
    loose = await put(client, boss, world, "rack", None, x=2)
    inside = (await client.post(f"{API}/assets", json={"type_id": world.types["couch"]["id"], "container_id": loose["id"]},
                                headers=boss)).json()
    await client.post(f"{API}/assets/{loose['id']}/files", files={"file": ("Фото.jpg", b"\xff\xd8", "image/jpeg")}, headers=boss)
    assert (await client.delete(f"{API}/assets/{loose['id']}", headers=keeper)).status_code == 404     # not theirs to see
    assert (await client.delete(f"{API}/assets/{loose['id']}", headers=world.person("v", ("viewer", "room", ROOM_A)))).status_code == 403
    assert (await client.delete(f"{API}/assets/{loose['id']}", headers=boss)).status_code == 204
    assert (await client.get(f"{API}/assets/{loose['id']}", headers=boss)).status_code == 404
    deleted = (await events(app, "assets.asset.deleted"))[-1]
    assert deleted["data"] == {"asset_id": loose["id"], "type_id": loose["type_id"]} and deleted["room_id"] == ROOM_A
    left = await get(client, boss, inside)                           # what stood inside waits to be placed
    assert (left["container_id"], left["needs_placement"], left["x"]) == (None, True, 2)
    # a row of several without numbers
    row = await client.post(f"{API}/assets/batch", json={"type_id": world.types["couch"]["id"], "floor_id": FLOOR,
                                                          "points": [[1, 1], [2, 1]]}, headers=boss)
    assert row.status_code == 201 and [a["inventory_no"] for a in row.json()["items"]] == [None, None]


async def test_many_at_once_with_numbers_in_a_row(client, world, boss):
    batch = {"type_id": world.types["couch"]["id"], "floor_id": FLOOR, "points": [[1, 1], [2, 1], [6, 1]],
             "prefix": "КШ-", "start": 9, "width": 3}
    r = await client.post(f"{API}/assets/batch", json=batch, headers=boss)
    assert r.status_code == 201
    assert [(a["inventory_no"], a["room_id"]) for a in r.json()["items"]] == [
        ("КШ-009", ROOM_A), ("КШ-010", ROOM_A), ("КШ-011", ROOM_B)]
    # one taken number refuses the whole lot
    clash = await client.post(f"{API}/assets/batch", json={**batch, "start": 11}, headers=boss)
    assert clash.status_code == 409
    assert (await client.get(f"{API}/assets", headers=boss)).json()["total"] == 3
    out = await client.post(f"{API}/assets/batch", json={**batch, "start": 50, "points": [[1, 1], [99, 1]]}, headers=boss)
    assert out.status_code == 422 and "2" in out.json()["detail"]


async def test_properties_by_rights(client, app, world, boss):
    a = await put(client, boss, world, "scope", "М-0001")
    url = f"{API}/assets/{a['id']}"
    keeper = world.person("keeper", ("responsible", "asset", a["id"]))
    card = await get(client, keeper, a)
    assert card["can"] == {"edit": True, "manage": False, "move": True} and card["portable"] is True
    assert [p["key"] for p in card["schema"]] == ["service_next", "made", "owner"]       # only what objects keep

    # whoever answers keeps the working data…
    r = await client.patch(url, json={"props": {"service_next": "2026-12-01"}, "note": "после ремонта", "version": 1},
                           headers=keeper)
    assert r.status_code == 200 and r.json()["props"] == {"owner": "Эндоскопия", "service_next": "2026-12-01"}
    # …but not what the administrator keeps: refused, naming the property
    r = await client.patch(url, json={"props": {"made": 2021}, "version": 2}, headers=keeper)
    assert r.status_code == 403 and "Год выпуска" in r.json()["detail"]
    assert (await client.patch(url, json={"inventory_no": "X", "version": 2}, headers=keeper)).status_code == 403
    assert (await client.patch(url, json={"props": {"made": 2021}, "version": 2}, headers=boss)).status_code == 200

    # what does not fit the schema
    for bad in ({"service_next": "скоро"}, {"made": "давно"}, {"nosuch": 1}, {"owner": None}, {"owner": ""}):
        r = await client.patch(url, json={"props": bad, "version": 3}, headers=boss)
        assert r.status_code == 422, bad
    assert (await client.patch(url, json={"props": {"made": None}, "version": 3}, headers=boss)).json()["props"] == {
        "owner": "Эндоскопия", "service_next": "2026-12-01"}                                # an optional one is emptied

    # two people at once: the second is told, not overwritten
    stale = await client.patch(url, json={"note": "x", "version": 1}, headers=boss)
    assert stale.status_code == 409 and stale.json()["current"]["version"] == 4
    # a viewer sees and changes nothing; a stranger does not even see
    viewer = world.person("viewer", ("viewer", "floor", FLOOR))
    assert (await get(client, viewer, a))["can"] == {"edit": False, "manage": False, "move": False}
    assert (await client.patch(url, json={"note": "x", "version": 4}, headers=viewer)).status_code == 403
    assert (await client.get(url, headers=world.person("stranger"))).status_code == 404
    changed = await events(app, "assets.asset.changed")
    assert changed[0]["data"]["fields"] == ["note", "props.service_next"]


async def test_state_responsible_and_history(client, app, world, boss):
    a = await put(client, boss, world, "scope", "М-0001")
    url = f"{API}/assets/{a['id']}"
    keeper = world.person("keeper")                                    # nobody yet
    assert (await client.get(url, headers=keeper)).status_code == 404

    r = await client.post(f"{url}/responsible", json={"person_id": world.persons["keeper"], "version": 1}, headers=boss)
    assert r.json()["responsible_id"] == world.persons["keeper"]
    event = (await events(app))[-1]
    assert event["type"] == "assets.asset.responsible_changed" and event["building_id"] == BUILDING
    assert event["data"] == {"asset_id": a["id"], "from": None, "to": world.persons["keeper"]}
    keeper = world.person("keeper", ("responsible", "asset", a["id"]))  # what the access service does on that event

    assert (await client.patch(url, json={"props": {"service_next": "2026-12-01"}, "version": 2}, headers=keeper)).status_code == 200
    faulty = await client.post(f"{url}/state", json={"state": "faulty", "version": 3}, headers=keeper)
    assert faulty.json()["state"] == "faulty"
    assert (await client.post(f"{url}/state", json={"state": "retired", "version": 4}, headers=keeper)).status_code == 403
    assert (await client.post(f"{url}/state", json={"state": "broken", "version": 4}, headers=keeper)).status_code == 422
    assert (await client.post(f"{url}/responsible", json={"person_id": None, "version": 4}, headers=keeper)).status_code == 403

    # the history: who, when, what it was and what it is
    items = (await client.get(f"{url}/history", headers=keeper)).json()["items"]
    assert [(h["action"], h["actor"]["id"]) for h in items] == [
        ("state", "keeper"), ("changed", "keeper"), ("responsible", "boss"), ("created", "boss")]
    assert items[0]["changes"] == {"state": ["in_use", "faulty"]} and items[1]["actor"]["person_id"] == world.persons["keeper"]
    assert items[1]["changes"] == {"props.service_next": [None, "2026-12-01"]}

    # the administrator takes the date back; whoever answers cannot
    change = items[1]["id"]
    assert (await client.post(f"{url}/history/{change}/revert", headers=keeper)).status_code == 403
    back = await client.post(f"{url}/history/{change}/revert", headers=boss)
    assert back.status_code == 200 and "service_next" not in back.json()["props"]
    assert (await client.get(f"{url}/history", headers=boss)).json()["items"][0]["reverts"] == change
    # what was changed since cannot be taken back
    assert (await client.post(f"{url}/history/{change}/revert", headers=boss)).json()["code"] == "changed_since"
    assert (await client.post(f"{url}/history/{items[3]['id']}/revert", headers=boss)).status_code == 404


async def test_moving(client, app, world, boss):
    scope = await put(client, boss, world, "scope", "М-0001", x=2)     # portable
    couch = await put(client, boss, world, "couch", "М-0002", x=2)     # stationary
    here = {"floor_id": FLOOR, "y": 2.0}
    keeper = world.person("keeper", ("responsible", "room", ROOM_A))

    # portable: whoever answers moves it — to a room they see
    blind = await client.post(f"{API}/assets/{scope['id']}/move", json={**here, "x": 7, "version": 1}, headers=keeper)
    assert blind.status_code == 403 and "помещению" in blind.json()["detail"]
    keeper = world.person("keeper", ("responsible", "room", ROOM_A), ("viewer", "room", ROOM_B))
    moved = await client.post(f"{API}/assets/{scope['id']}/move", json={**here, "x": 7, "version": 1}, headers=keeper)
    assert moved.status_code == 200 and (moved.json()["room_id"], moved.json()["x"]) == (ROOM_B, 7)
    event = (await events(app, "assets.asset.moved"))[-1]
    assert (event["data"]["from_room_id"], event["data"]["to_room_id"], event["room_id"]) == (ROOM_A, ROOM_B, ROOM_B)
    # stationary: only the administrator
    fixed = await client.post(f"{API}/assets/{couch['id']}/move", json={**here, "x": 3, "version": 1}, headers=keeper)
    assert fixed.status_code == 403 and "администратор" in fixed.json()["detail"]
    assert (await client.post(f"{API}/assets/{couch['id']}/move", json={**here, "x": 3, "version": 1}, headers=boss)).status_code == 200
    out = await client.post(f"{API}/assets/{couch['id']}/move", json={**here, "x": 60, "version": 2}, headers=boss)
    assert out.status_code == 422 and out.json()["code"] == "outside"


async def test_container(client, app, world, boss):
    rack = await put(client, boss, world, "rack", "СТ-1", x=2)
    box = {"type_id": world.types["scope"]["id"], "container_id": rack["id"], "props": {"owner": "x"}}
    inside = (await client.post(f"{API}/assets", json={**box, "inventory_no": "М-0001"}, headers=boss)).json()
    assert (inside["container_id"], inside["room_id"], inside["x"]) == (rack["id"], ROOM_A, None)
    assert [c["id"] for c in (await get(client, boss, rack))["children"]] == [inside["id"]]
    # only a container takes others in, and not one that is inside another
    couch = await put(client, boss, world, "couch", "М-0002")
    for wrong in (couch["id"], inside["id"]):
        r = await client.post(f"{API}/assets", json={**box, "container_id": wrong, "inventory_no": "М-0009"}, headers=boss)
        assert r.status_code == 422

    # the container moves: what is inside goes with it
    await client.post(f"{API}/assets/{rack['id']}/move", json={"floor_id": FLOOR, "x": 7, "y": 2, "version": 1}, headers=boss)
    assert (await get(client, boss, inside))["room_id"] == ROOM_B
    # the container is retired: what was inside stays in the room, to be placed anew
    await client.post(f"{API}/assets/{rack['id']}/state", json={"state": "retired", "version": 2}, headers=boss)
    left = await get(client, boss, inside)
    assert (left["container_id"], left["needs_placement"], left["x"], left["room_id"]) == (None, True, 7, ROOM_B)
    found = await client.get(f"{API}/assets", params={"needs_placement": True}, headers=boss)
    assert [x["id"] for x in found.json()["items"]] == [inside["id"]]
    # placed again: the mark is gone
    put_back = await client.post(f"{API}/assets/{inside['id']}/move",
                                 json={"floor_id": FLOOR, "x": 6, "y": 1, "version": left["version"]}, headers=boss)
    assert put_back.json()["needs_placement"] is False


async def test_files_and_qr(client, world, boss):
    a = await put(client, boss, world, "scope", "М-0001")
    url = f"{API}/assets/{a['id']}/files"
    photo = await client.post(url, files={"file": ("Фото.jpg", b"\xff\xd8jpeg", "image/jpeg")}, headers=boss)
    paper = await client.post(url, files={"file": ("Паспорт.pdf", b"%PDF-1.4", "application/pdf")}, headers=boss)
    assert (photo.json()["kind"], paper.json()["kind"]) == ("photo", "document")
    viewer = world.person("viewer", ("viewer", "room", ROOM_A))
    assert [f["name"] for f in (await client.get(url, headers=viewer)).json()["items"]] == ["Фото.jpg", "Паспорт.pdf"]
    got = await client.get(f"{API}/files/{paper.json()['id']}", headers=viewer)
    assert got.content == b"%PDF-1.4" and got.headers["content-type"] == "application/pdf"
    assert (await client.post(url, files={"file": ("x.jpg", b"1", "image/jpeg")}, headers=viewer)).status_code == 403
    assert (await client.post(url, files={"file": ("x.jpg", b"", "image/jpeg")}, headers=boss)).status_code == 422
    stranger = world.person("stranger")
    assert (await client.get(f"{API}/files/{paper.json()['id']}", headers=stranger)).status_code == 404
    assert (await client.delete(f"{API}/files/{photo.json()['id']}", headers=boss)).status_code == 204
    actions = [h["action"] for h in (await client.get(f"{API}/assets/{a['id']}/history", headers=boss)).json()["items"]]
    assert actions == ["file_removed", "file_added", "file_added", "created"]

    # the QR code on the sticker: to its object for those who may see it, to nothing for the rest
    assert (await client.get(f"{API}/qr/{a['qr_code'].lower()}", headers=viewer)).json()["asset_id"] == a["id"]
    assert (await client.get(f"{API}/qr/{a['qr_code']}", headers=stranger)).status_code == 404
    assert (await client.get(f"{API}/qr/NOSUCHCODE", headers=boss)).status_code == 404


async def test_lists_filters_and_what_one_sees(client, world, boss):
    one = await put(client, boss, world, "scope", "М-0001", x=2, props={"owner": "x", "service_next": "2026-10-20"})
    two = await put(client, boss, world, "scope", "М-0002", x=7, props={"owner": "x", "service_next": "2027-03-01"},
                    serial_no="SN-777")
    couch = await put(client, boss, world, "couch", "КШ-1", x=7)
    await client.post(f"{API}/assets/{couch['id']}/state", json={"state": "faulty", "version": 1}, headers=boss)

    async def ids(headers=boss, **params) -> list[str]:
        return [a["inventory_no"] for a in (await client.get(f"{API}/assets", params=params, headers=headers)).json()["items"]]

    assert await ids() == ["М-0001", "М-0002", "КШ-1"]                 # by type, then by number
    assert await ids(room_id=ROOM_B) == ["М-0002", "КШ-1"]
    assert await ids(state="faulty") == ["КШ-1"] and await ids(type_id=world.types["couch"]["id"]) == ["КШ-1"]
    assert await ids(q="sn-7") == ["М-0002"] and await ids(q="гастро") == ["М-0001", "М-0002"]
    # by a value of a property: whose service is due before November
    assert await ids(**{"prop.service_next.lte": "2026-10-31"}) == ["М-0001"]
    assert await ids(**{"prop.service_next.gte": "2026-11-01"}) == ["М-0002"]
    assert await ids(limit=2) == ["М-0001", "М-0002"] and await ids(limit=2, cursor=2) == ["КШ-1"]

    # one sees what is in one's areas and what one answers for
    assert await ids(world.person("a", ("viewer", "room", ROOM_A))) == ["М-0001"]
    assert await ids(world.person("b", ("responsible", "asset", two["id"]))) == ["М-0002"]
    assert await ids(world.person("f", ("viewer", "floor", FLOOR))) == ["М-0001", "М-0002", "КШ-1"]
    assert await ids(world.person("nobody")) == []
    batch = await client.post(f"{API}/assets/batch-get", json={"ids": [one["id"], two["id"]]},
                              headers=world.person("a", ("viewer", "room", ROOM_A)))
    assert [a["id"] for a in batch.json()["items"]] == [one["id"]]

    usage = await client.get(f"{API}/usage", params={"type_id": world.types["scope"]["id"], "prop": "service_next"},
                             headers=world.tokens.bearer("svc", login="twin-svc-catalog", service=True))
    assert usage.json() == {"assets": 2, "with_value": 2}
    assert (await client.get(f"{API}/usage", params={"type_id": one["type_id"]}, headers=boss)).status_code == 403


async def test_following_other_services(client, app, world, boss):
    a = await put(client, boss, world, "scope", "М-0001")
    bus = app.state.bus

    def event(type_: str, data: dict) -> dict:
        return envelope(type_, ("x", "1"), data, actor={"kind": "service", "id": "other"})

    # the catalog adds a required property: objects of the type are marked «to be filled in», and found by that
    kind = world.types["scope"]
    kind["schema"].append(prop("leak_tested", "Проверка на герметичность", "date", required=True))
    kind["schema_version"] = 2
    await bus.handle("type-changed", event("catalog.type.changed", {
        "type_id": kind["id"], "name": kind["name"], "category_id": kind["category_id"], "schema_version": 2,
        "schema_changed": True, "container": False, "portable": True}))
    marked = await get(client, boss, a)
    assert marked["needs_fill"] is True and marked["schema_version"] == 2 and marked["schema"][-1]["key"] == "leak_tested"
    found = await client.get(f"{API}/assets", params={"needs_fill": True}, headers=boss)
    assert [x["id"] for x in found.json()["items"]] == [a["id"]]
    filled = await client.patch(f"{API}/assets/{a['id']}", json={"props": {"leak_tested": "2026-10-01"},
                                                               "version": marked["version"]}, headers=boss)
    assert filled.json()["needs_fill"] is False

    # the room is gone from the drawing: the object stays attached to it, to be placed anew
    await bus.handle("room-retired", event("buildings.room.retired", {"room_id": ROOM_A, "floor_id": FLOOR}))
    assert (await get(client, boss, a))["needs_placement"] is True
    # whoever answered has left
    person = str(uuid4())
    now = await get(client, boss, a)
    await client.post(f"{API}/assets/{a['id']}/responsible", json={"person_id": person, "version": now["version"]}, headers=boss)
    await bus.handle("person-left", event("people.person.left", {"person_id": person}))
    assert (await get(client, boss, a))["responsible_id"] is None
    last = (await client.get(f"{API}/assets/{a['id']}/history", headers=boss)).json()["items"][0]
    assert (last["action"], last["actor"]["kind"], last["reason"]) == ("system", "service", "Ответственный выбыл")


async def test_neighbours_away(client, world, boss):
    a = await put(client, boss, world, "scope", "М-0001")
    body = {"type_id": world.types["scope"]["id"], "floor_id": FLOOR, "x": 2, "y": 2, "inventory_no": "М-0002",
            "props": {"owner": "x"}}
    # without the catalog: objects of known types are read and edited
    world.up["catalog"] = False
    assert (await get(client, boss, a))["schema"]
    assert (await client.patch(f"{API}/assets/{a['id']}", json={"props": {"made": 2020}, "version": 1}, headers=boss)).status_code == 200
    assert (await client.post(f"{API}/assets", json=body, headers=boss)).status_code == 201
    # without buildings: only placing and moving stop — and say why
    world.up["buildings"] = False
    down = await client.post(f"{API}/assets", json={**body, "inventory_no": "М-0003"}, headers=boss)
    assert down.status_code == 503 and down.json()["service"] == "buildings"
    move = await client.post(f"{API}/assets/{a['id']}/move", json={"floor_id": FLOOR, "x": 3, "y": 2, "version": 2}, headers=boss)
    assert move.status_code == 503
    assert (await client.get(f"{API}/assets", headers=boss)).json()["total"] == 2
    assert (await client.post(f"{API}/assets/{a['id']}/state", json={"state": "faulty", "version": 2}, headers=boss)).status_code == 200


def workbook(*rows) -> bytes:
    import io

    from openpyxl import Workbook
    wb = Workbook()
    for row in (("Тип", "Инвентарный номер", "Серийный номер", "Этаж", "X", "Y", "Примечание"), *rows):
        wb.active.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


async def test_import_from_excel_is_all_or_nothing(client, world, boss):
    async def load(data: bytes, headers=boss):
        return await client.post(f"{API}/assets/import", params={"building_id": BUILDING},
                                 files={"file": ("objects.xlsx", data)}, headers=headers)

    await put(client, boss, world, "couch", "КШ-1")
    good = [("Кушетка", "КШ-2", None, 1, 2, 2, "у окна"), ("кушетка", "КШ-3", "SN-9", "План 1-го этажа", 7.5, 2, None),
            ("Кушетка", None, None, 1, 3, 2, "без учёта")]
    bad = [("Кушетка", "КШ-1", None, 1, 2, 2, None),            # the number is taken
           ("Диван", "КШ-4", None, 1, 2, 2, None),              # no such type
           ("Кушетка", "КШ-5", None, 9, 2, 2, None),            # no such floor
           ("Кушетка", "КШ-6", None, 1, 99, 2, None),           # outside the rooms
           ("Кушетка", "КШ-2", None, 1, "два", 2, None),        # the number twice in the file, not a number
           (None, None, None, None, None, None, None)]
    r = await load(workbook(*good, *bad))
    assert r.status_code == 422
    report = {e["field"]: e["message"] for e in r.json()["errors"]}
    assert sorted(report) == ["строка 5", "строка 6", "строка 7", "строка 8", "строка 9"]
    assert "уже есть" in report["строка 5"] and "нет типа" in report["строка 6"] and "вне помещений" in report["строка 8"]
    assert "повторяется" in report["строка 9"] and "числами" in report["строка 9"]
    assert (await client.get(f"{API}/assets", headers=boss)).json()["total"] == 1          # nothing was created

    r = await load(workbook(*good))
    assert r.status_code == 201 and r.json() == {"created": 3}
    items = (await client.get(f"{API}/assets", params={"q": "куш"}, headers=boss)).json()["items"]
    assert [(a["inventory_no"], a["room_id"], a["serial_no"], a["note"]) for a in items] == [
        ("КШ-1", ROOM_A, None, ""), ("КШ-2", ROOM_A, None, "у окна"), ("КШ-3", ROOM_B, "SN-9", ""), (None, ROOM_A, None, "без учёта")]
    assert (await load(workbook(*good))).status_code == 422                                # again: the numbers are taken
    assert (await load(b"not a workbook")).status_code == 422
    assert (await load(workbook(*good), world.person("viewer", ("viewer", "floor", FLOOR)))).status_code == 403
    assert (await load(workbook(*good), world.person("stranger"))).status_code == 404


async def test_card_shows_what_is_kept_with_the_type(client, world, boss):
    world.types["scope"]["values"] = {"maker": "Olympus"}
    a = await put(client, boss, world, "scope", "М-0001")
    card = await get(client, boss, a)
    assert [(p["title"], p["value"]) for p in card["type_props"]] == [("Производитель", "Olympus")]


async def test_labels_are_pdf_and_only_for_those_who_see(client, world, boss):
    a = await put(client, boss, world, "scope", "QR-0001", x=2.0)
    b = await put(client, boss, world, "couch", "QR-0002", x=2.5)
    one = await client.get(f"{API}/assets/{a['id']}/label?size=40", headers=boss)
    assert one.status_code == 200 and one.headers["content-type"] == "application/pdf" and one.content.startswith(b"%PDF")
    viewer = world.person("viewer", ("viewer", "room", ROOM_A))
    assert (await client.get(f"{API}/assets/{a['id']}/label", headers=viewer)).status_code == 200
    assert (await client.get(f"{API}/assets/{a['id']}/label", headers=world.person("stranger"))).status_code == 404
    assert (await client.get(f"{API}/assets/{a['id']}/label?size=5", headers=boss)).status_code == 422
    sheet = await client.post(f"{API}/labels", json={"room_id": ROOM_A, "size": 30}, headers=boss)
    assert sheet.status_code == 200 and sheet.content.startswith(b"%PDF")
    chosen = await client.post(f"{API}/labels", json={"asset_ids": [a["id"], b["id"]]}, headers=boss)
    assert chosen.status_code == 200
    # a sheet is printed by whoever manages the objects, not by whoever only looks
    assert (await client.post(f"{API}/labels", json={"room_id": ROOM_A}, headers=viewer)).status_code == 403
    assert (await client.post(f"{API}/labels", json={"room_id": ROOM_B}, headers=boss)).status_code == 404


async def test_responsibles_for_the_reconciliation_of_rights(client, world, boss, tokens):
    a = await put(client, boss, world, "scope", "RS-0001", x=2.0)
    keeper = world.person("keeper", ("viewer", "room", ROOM_A))
    person = world.persons["keeper"]
    await client.post(f"{API}/assets/{a['id']}/responsible", json={"person_id": person, "version": a["version"]}, headers=boss)
    svc = tokens.bearer("svc", service=True, login="twin-svc-access")
    rows = (await client.get(f"{API}/responsibles", headers=svc)).json()["items"]
    assert rows == [{"asset_id": a["id"], "person_id": person, "building_id": BUILDING}]
    assert (await client.get(f"{API}/responsibles", headers=keeper)).status_code == 403


async def test_a_new_revision_of_the_drawing_rehouses_objects_by_their_points(client, app, world, boss):
    from twin_chassis.events import envelope
    a = await put(client, boss, world, "scope", "РВ-0001", x=2.0)
    b = await put(client, boss, world, "couch", "РВ-0002", x=7.0)
    c = await put(client, boss, world, "couch", "РВ-0003", x=8.0)
    box = await put(client, boss, world, "rack", "РВ-0004", x=7.5)
    inner = await client.post(f"{API}/assets/{a['id']}/move", headers=boss,
                              json={"container_id": box["id"], "version": a["version"]})
    assert inner.status_code == 200
    # the new revision: room B split at x = 7.5 into B (left) and C (right); the part beyond x = 9 is gone
    room_c = str(uuid4())
    world.room_at = lambda x: ROOM_A if 0 <= x < 5 else ROOM_B if 5 <= x < 7.6 else room_c if 7.6 <= x < 8.5 else None
    data = {"revision_id": str(uuid4()), "drawing_id": str(uuid4()), "build_id": str(uuid4()),
            "floors": {"created": [], "retired": [], "active": [FLOOR]},
            "rooms": {"created": [room_c], "changed": [{"id": ROOM_B, "outline": True}], "retired": []}}
    event = envelope("buildings.revision.published", ("revision", data["revision_id"]), data,
                     actor={"kind": "service", "id": "buildings"}, building_id=BUILDING)
    assert await app.state.bus.handle("revision-published", event) is True
    now = {x["inventory_no"]: x for x in (await client.get(f"{API}/assets", params={"building_id": BUILDING},
                                                           headers=boss)).json()["items"]}
    assert now["РВ-0002"]["room_id"] == ROOM_B and not now["РВ-0002"]["needs_placement"]
    assert now["РВ-0003"]["room_id"] == room_c
    assert now["РВ-0004"]["room_id"] == ROOM_B and now["РВ-0001"]["room_id"] == ROOM_B     # inside the rack, with it
    history = (await client.get(f"{API}/assets/{c['id']}/history", headers=boss)).json()["items"]
    assert history[0]["action"] == "moved" and history[0]["reason"] == "Помещение уточнено по новой версии чертежа"
    # the next revision takes the right part away: what stood there waits to be placed, and is found by the filter
    world.room_at = lambda x: ROOM_A if 0 <= x < 5 else ROOM_B if 5 <= x < 7.6 else None
    data = {**data, "revision_id": str(uuid4()),
            "rooms": {"created": [], "changed": [], "retired": [room_c]}}
    event = envelope("buildings.revision.published", ("revision", data["revision_id"]), data,
                     actor={"kind": "service", "id": "buildings"}, building_id=BUILDING)
    assert await app.state.bus.handle("revision-published", event) is True
    waiting = (await client.get(f"{API}/assets", params={"needs_placement": "true"}, headers=boss)).json()["items"]
    assert [x["inventory_no"] for x in waiting] == ["РВ-0003"] and waiting[0]["room_id"] == room_c
    # a revision aligning the floor 1 m further: the points move with it, and so into the next room
    data = {**data, "revision_id": str(uuid4()), "rooms": {"created": [], "changed": [], "retired": []},
            "moves": {FLOOR: [-1.0, 0.0]}}
    event = envelope("buildings.revision.published", ("revision", data["revision_id"]), data,
                     actor={"kind": "service", "id": "buildings"}, building_id=BUILDING)
    assert await app.state.bus.handle("revision-published", event) is True
    now = await get(client, boss, b)
    assert (now["x"], now["room_id"]) == (6.0, ROOM_B)


async def test_merged_and_split_rooms_carry_their_objects(client, app, world, boss):
    from twin_chassis.events import envelope
    a = await put(client, boss, world, "couch", "ОБ-0001", x=2.0)
    b = await put(client, boss, world, "couch", "ОБ-0002", x=7.0)
    merged = envelope("buildings.room.merged", ("room", ROOM_A), {"from": [ROOM_B], "into": ROOM_A, "floor_id": FLOOR},
                      actor={"kind": "user", "id": "boss"}, building_id=BUILDING, floor_id=FLOOR, room_id=ROOM_A)
    assert await app.state.bus.handle("room-merged", merged) is True
    assert (await get(client, boss, b))["room_id"] == ROOM_A
    # split again: the object at x = 7 goes to the new part
    part = str(uuid4())
    world.room_at = lambda x: ROOM_A if 0 <= x < 5 else part if 5 <= x < 10 else None
    split = envelope("buildings.room.split", ("room", ROOM_A),
                     {"from": ROOM_A, "into": [part], "heir": ROOM_A, "floor_id": FLOOR},
                     actor={"kind": "user", "id": "boss"}, building_id=BUILDING, floor_id=FLOOR, room_id=ROOM_A)
    assert await app.state.bus.handle("room-split", split) is True
    assert (await get(client, boss, a))["room_id"] == ROOM_A and (await get(client, boss, b))["room_id"] == part


async def test_a_guest_of_a_floor_sees_its_objects_but_not_who_is_behind_them(client, world, boss, tokens):
    world.types["desk"] = kind("Стол", prop("user", "Кто сидит", "person"), prop("size", "Ширина", "number"))
    here = await put(client, boss, world, "desk", "СТ-0001", x=2.0, note="стол Иванова", props={"user": "Иванов", "size": 120})
    await client.post(f"{API}/assets/{here['id']}/responsible", json={"person_id": str(uuid4()), "version": 1}, headers=boss)
    beside = await put(client, boss, world, "couch", "КШ-0001", x=7.0)
    above = await put(client, boss, world, "couch", "КШ-0002", floor_id=FLOOR_2)
    assert above["room_id"] == ROOM_C
    guest = tokens.guest("floor", FLOOR, BUILDING, FLOOR)

    async def numbers(**params) -> list[str]:
        r = await client.get(f"{API}/assets", params=params, headers=guest)
        assert r.status_code == 200, r.text
        return [a["inventory_no"] for a in r.json()["items"]]

    # the objects of its floor, however asked; of the floor above — nothing
    assert await numbers() == ["КШ-0001", "СТ-0001"]
    assert await numbers(building_id=BUILDING) == ["КШ-0001", "СТ-0001"]
    assert await numbers(floor_id=FLOOR_2) == [] and await numbers(room_id=ROOM_C) == []
    assert (await client.get(f"{API}/assets/{above['id']}", headers=guest)).status_code == 404
    batch = await client.post(f"{API}/assets/batch-get", json={"ids": [here["id"], above["id"]]}, headers=guest)
    assert [a["id"] for a in batch.json()["items"]] == [here["id"]]

    # what the object is, where and in what state — yes; who answers for it, notes, a person in a property — no
    card = await get(client, guest, here)
    for seen in (card, batch.json()["items"][0], (await client.get(f"{API}/assets", headers=guest)).json()["items"][1]):
        assert "responsible_id" not in seen and "note" not in seen and "created_by" not in seen
        assert (seen["type_name"], seen["inventory_no"], seen["room_id"], seen["state"]) == ("Стол", "СТ-0001", ROOM_A, "in_use")
        assert seen["props"] == {"size": 120}
    assert card["can"] == {"edit": False, "manage": False, "move": False}
    # nor may it find out by a filter
    for params in ({"responsible_id": str(uuid4())}, {"prop.user": "Иванов"}):
        r = await client.get(f"{API}/assets", params=params, headers=guest)
        assert r.status_code == 403 and r.json()["code"] == "guest"
    # whoever has an account still sees it all
    full = await get(client, boss, here)
    assert full["note"] == "стол Иванова" and full["responsible_id"] and full["props"]["user"] == "Иванов"

    # a guest of a room sees that room only; of the whole building — every floor
    assert [a["id"] for a in (await client.get(f"{API}/assets", headers=tokens.guest("room", ROOM_B, BUILDING, FLOOR))
                              ).json()["items"]] == [beside["id"]]
    whole = (await client.get(f"{API}/assets", headers=tokens.guest("building", BUILDING, BUILDING))).json()
    assert whole["total"] == 3
    stranger = tokens.guest("building", str(uuid4()), str(uuid4()))
    assert (await client.get(f"{API}/assets", headers=stranger)).json()["items"] == []
    assert (await client.get(f"{API}/assets/{here['id']}", headers=stranger)).status_code == 404


async def test_a_guest_gets_no_history_files_labels_or_changes(client, world, boss, tokens):
    a = await put(client, boss, world, "scope", "М-0001", x=2.0)
    photo = (await client.post(f"{API}/assets/{a['id']}/files", files={"file": ("Фото.jpg", b"\xff\xd8", "image/jpeg")},
                               headers=boss)).json()
    entry = (await client.get(f"{API}/assets/{a['id']}/history", headers=boss)).json()["items"][0]
    guest = tokens.guest("building", BUILDING, BUILDING)
    url, file = f"{API}/assets/{a['id']}", {"file": ("x.jpg", b"1", "image/jpeg")}
    place = {"type_id": a["type_id"], "floor_id": FLOOR, "x": 2, "y": 2, "inventory_no": "М-0002", "props": {"owner": "x"}}
    asks = [
        ("GET", f"{url}/history", {}), ("POST", f"{url}/history/{entry['id']}/revert", {}),
        ("GET", f"{url}/files", {}), ("GET", f"{API}/files/{photo['id']}", {}), ("POST", f"{url}/files", {"files": file}),
        ("DELETE", f"{API}/files/{photo['id']}", {}), ("GET", f"{url}/label", {}),
        ("POST", f"{API}/labels", {"json": {"building_id": BUILDING}}), ("GET", f"{API}/qr/{a['qr_code']}", {}),
        ("GET", f"{API}/responsibles", {}), ("GET", f"{API}/usage", {"params": {"type_id": a["type_id"]}}),
        ("POST", f"{API}/assets/import", {"params": {"building_id": BUILDING}, "files": file}),
        ("POST", f"{API}/assets", {"json": place}),
        ("POST", f"{API}/assets/batch", {"json": {"type_id": a["type_id"], "floor_id": FLOOR, "points": [[1, 1]],
                                                  "prefix": "Г-", "start": 1}}),
        # a stale version would have answered 409 with the whole object — a guest is refused before that
        ("PATCH", url, {"json": {"note": "x", "version": 99}}),
        ("POST", f"{url}/state", {"json": {"state": "faulty", "version": 1}}),
        ("POST", f"{url}/responsible", {"json": {"person_id": None, "version": 1}}),
        ("POST", f"{url}/move", {"json": {"floor_id": FLOOR, "x": 7, "y": 2, "version": 1}}),
    ]
    for method, path, kw in asks:
        r = await client.request(method, path, headers=guest, **kw)
        assert (r.status_code, r.json()["code"]) == (403, "guest"), (method, path, r.text)
    # nothing changed meanwhile
    assert (await get(client, boss, a))["version"] == 1


async def test_free_inventory_numbers_for_one_who_has_none(client, world, boss, tokens):
    url = f"{API}/inventory-numbers"
    couch = world.types["couch"]["id"]
    # a type without objects starts its series from the first letters of its name
    assert (await client.get(url, params={"type_id": couch}, headers=boss)).json() == {"numbers": ["К-00001"]}
    await put(client, boss, world, "couch", "К-00001")
    # then the series goes on, past numbers taken by anything (an object of another type here)
    await put(client, boss, world, "rack", "К-00003")
    assert (await client.get(url, params={"type_id": couch, "count": 3}, headers=boss)).json() == \
        {"numbers": ["К-00004", "К-00005", "К-00006"]}
    # the series of the last object of the type, its own width
    await put(client, boss, world, "couch", "КШ-17")
    assert (await client.get(url, params={"type_id": couch}, headers=boss)).json() == {"numbers": ["КШ-18"]}
    guest = tokens.guest("building", BUILDING, BUILDING)
    assert (await client.get(url, params={"type_id": couch}, headers=guest)).status_code == 403


async def test_the_make_and_model_of_an_object(client, app, world, boss):
    """A type says what the object is; a product of the catalog — which make and model, if it is named."""
    by_vendor = {p["vendor"]: p for p in world.products.values()}
    km, old, rack = by_vendor["Медстальконструкция"], by_vendor[""], by_vendor["ЦМО"]
    a = await put(client, boss, world, "couch", "К-0001", product_id=km["id"])
    assert (a["product_id"], a["product_name"]) == (km["id"], "Медстальконструкция КМ-01")
    plain = await put(client, boss, world, "couch", "К-0002", x=3.0)
    assert (plain["product_id"], plain["product_name"]) == (None, "")
    # of another type, archived or unknown — refused
    body = {"type_id": world.types["couch"]["id"], "floor_id": FLOOR, "x": 2, "y": 2, "inventory_no": "К-0003"}
    for wrong in (rack["id"], old["id"], str(uuid4())):
        r = await client.post(f"{API}/assets", json={**body, "product_id": wrong}, headers=boss)
        assert r.status_code == 422 and r.json()["errors"][0]["field"] == "product_id", wrong
    # the card describes the product; the list finds by its name and filters by it
    card = await get(client, boss, a)
    assert (card["product"]["article"], card["product"]["price"]) == ("KM01", 15000.0)
    assert (await get(client, boss, plain))["product"] is None
    found = (await client.get(f"{API}/assets", params={"building_id": BUILDING, "q": "КМ-01"}, headers=boss)).json()["items"]
    assert [x["inventory_no"] for x in found] == ["К-0001"]
    by_product = (await client.get(f"{API}/assets", params={"product_id": km["id"]}, headers=boss)).json()["items"]
    assert [x["inventory_no"] for x in by_product] == ["К-0001"]
    # the administrator names or clears the model; it goes to the history
    r = await client.patch(f"{API}/assets/{plain['id']}", json={"product_id": km["id"], "version": plain["version"]}, headers=boss)
    assert r.status_code == 200 and r.json()["product_name"] == "Медстальконструкция КМ-01"
    r = await client.patch(f"{API}/assets/{plain['id']}", json={"product_id": None, "version": r.json()["version"]}, headers=boss)
    assert r.status_code == 200 and r.json()["product_id"] is None
    history = (await client.get(f"{API}/assets/{plain['id']}/history", headers=boss)).json()["items"]
    assert history[0]["changes"]["product_name"] == ["Медстальконструкция КМ-01", ""]
    keeper = world.person("keeper", ("responsible", "asset", a["id"]))
    r = await client.patch(f"{API}/assets/{a['id']}", json={"product_id": None, "version": a["version"]}, headers=keeper)
    assert r.status_code == 403
    # renamed in the catalog: the copies follow
    event = envelope("catalog.product.changed", ("product", km["id"]), {**{k: km[k] for k in ("product_id", "type_id") if k in km},
                     "product_id": km["id"], "type_id": km["type_id"], "vendor": "МСК", "name": "КМ-01", "article": "KM01",
                     "price": 15000.0, "currency": "RUB", "active": True}, actor={"kind": "service", "id": "catalog"})
    assert await app.state.bus.handle("product-changed", event) is True
    assert (await get(client, boss, a))["product_name"] == "МСК КМ-01"
