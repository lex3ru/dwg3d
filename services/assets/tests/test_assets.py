"""Objects on the plan: placing, properties by rights, state, moving, history, files."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from twin_chassis.db import outbox
from twin_chassis.events import envelope

from .conftest import API, BUILDING, FLOOR, ROOM_A, ROOM_B, prop, put


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
    good = [("Кушетка", "КШ-2", None, 1, 2, 2, "у окна"), ("кушетка", "КШ-3", "SN-9", "План 1-го этажа", 7.5, 2, None)]
    bad = [("Кушетка", "КШ-1", None, 1, 2, 2, None),            # the number is taken
           ("Диван", "КШ-4", None, 1, 2, 2, None),              # no such type
           ("Кушетка", "КШ-5", None, 9, 2, 2, None),            # no such floor
           ("Кушетка", "КШ-6", None, 1, 99, 2, None),           # outside the rooms
           ("Кушетка", "КШ-2", None, 1, "два", 2, None),        # the number twice in the file, not a number
           (None, None, None, None, None, None, None)]
    r = await load(workbook(*good, *bad))
    assert r.status_code == 422
    report = {e["field"]: e["message"] for e in r.json()["errors"]}
    assert sorted(report) == ["строка 4", "строка 5", "строка 6", "строка 7", "строка 8"]
    assert "уже есть" in report["строка 4"] and "нет типа" in report["строка 5"] and "вне помещений" in report["строка 7"]
    assert "повторяется" in report["строка 8"] and "числами" in report["строка 8"]
    assert (await client.get(f"{API}/assets", headers=boss)).json()["total"] == 1          # nothing was created

    r = await load(workbook(*good))
    assert r.status_code == 201 and r.json() == {"created": 2}
    items = (await client.get(f"{API}/assets", params={"q": "КШ"}, headers=boss)).json()["items"]
    assert [(a["inventory_no"], a["room_id"], a["serial_no"], a["note"]) for a in items] == [
        ("КШ-1", ROOM_A, None, ""), ("КШ-2", ROOM_A, None, "у окна"), ("КШ-3", ROOM_B, "SN-9", "")]
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
