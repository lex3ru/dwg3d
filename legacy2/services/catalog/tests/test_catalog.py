"""Types, property sets, schemas, models."""
from __future__ import annotations

import json
import struct

from sqlalchemy import select
from twin_chassis.db import outbox
from twin_chassis.migrate import upgrade

from app import seed

from .conftest import API


async def events(app) -> list[dict]:
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        return [e for (e,) in rows]


def prop(key: str, title: str = "Свойство", kind: str = "text", **kw) -> dict:
    return {"key": key, "title": title, "kind": kind, **kw}


async def named(client, headers, path: str) -> dict[str, dict]:
    return {x["name"]: x for x in (await client.get(f"{API}/{path}", headers=headers)).json()["items"]}


async def test_what_the_catalog_starts_with(client, tokens, database_url):
    user = tokens.bearer("user-1")                       # reading is open to anyone signed in
    assert sorted(await named(client, user, "categories")) == sorted(
        ["Мебель", "Медицинская техника"] + [c["name"] for c in seed.EXTRA_CATEGORIES + seed.OFFICE_CATEGORIES])
    assert sorted(await named(client, user, "property-sets")) == sorted(
        ["Мебель", "Медицинское изделие", "Учёт"] + [x["name"] for x in seed.EXTRA_SETS + seed.OFFICE_SETS])
    types = await named(client, user, "types")
    first = ["Аппарат КТ", "Гастроскоп", "Кресло посетителя", "Кушетка", "Рабочий стол"]
    seeded = first + [t["name"] for t in seed.MORE_TYPES + seed.OFFICE_TYPES]
    assert set(first) <= set(types) and sorted(types) == sorted(seeded)
    # the office: a projector hangs on the ceiling, a monitor stands on the desk, the equipment has its own set
    assert types["Проектор потолочный"]["ceiling_mounted"] and types["Монитор 27″"]["elevation"] == 0.75
    shredder = (await client.get(f"{API}/types/{types['Шредер']['id']}/schema", headers=user)).json()
    assert [p["set"] for p in shredder["properties"]][-1] == "Оргтехника"
    assert types["Гастроскоп"]["portable"] and types["Аппарат КТ"]["container"] and not types["Кушетка"]["portable"]
    # a ceiling light hangs under the ceiling, a sconce on the wall
    panel, sconce = types["Светильник светодиодный, панель 600×600"], types["Светильник настенный (бра)"]
    assert (panel["ceiling_mounted"], panel["wall_mounted"]) == (True, False)
    assert (sconce["ceiling_mounted"], sconce["wall_mounted"]) == (False, True)

    # the schema: the properties of the sets in their order, then the type's own
    schema = (await client.get(f"{API}/types/{types['Гастроскоп']['id']}/schema", headers=user)).json()
    keys = [p["key"] for p in schema["properties"]]
    assert keys[:3] == ["commissioned", "warranty_until", "manufacturer"] and keys[-1] == "repairs"
    assert [p["set"] for p in schema["properties"]][:3] == ["Учёт", "Учёт", "Медицинское изделие"]
    by_key = {p["key"]: p for p in schema["properties"]}
    # who edits what: the administrator keeps the records, whoever answers keeps the working data
    assert (by_key["service_next"]["editable_by"], by_key["warranty_until"]["editable_by"]) == ("responsible", "admin")
    assert (by_key["scope_kind"]["stored"], by_key["examinations"]["stored"]) == ("type", "asset")

    # a start over the same database changes nothing: what administrators did stays
    admin = tokens.admin()
    couch = types["Кушетка"]
    body = {**{k: couch[k] for k in ("category_id", "sets", "properties", "values")}, "name": "Кушетка смотровая",
            "w": 1.9, "d": 0.65, "h": 0.55, "version": couch["version"]}
    assert (await client.patch(f"{API}/types/{couch['id']}", json=body, headers=admin)).status_code == 200
    upgrade(database_url, "migrations")
    assert "Кушетка смотровая" in await named(client, user, "types")
    assert len(await named(client, user, "types")) == 5 + len(seed.MORE_TYPES) + len(seed.OFFICE_TYPES)


async def test_only_the_system_administrator_changes(client, tokens):
    assert (await client.get(f"{API}/types")).status_code == 401
    user = tokens.bearer("user-1")
    types = await named(client, user, "types")
    one = types["Кушетка"]["id"]
    for method, path, body in (("POST", "categories", {"name": "x"}), ("POST", "property-sets", {"name": "x"}),
                               ("POST", "types", {}), ("POST", f"types/{one}/archive", None),
                               ("DELETE", f"types/{one}/model", None)):
        r = await client.request(method, f"{API}/{path}", json=body, headers=user)
        assert r.status_code == 403, path
    service = tokens.bearer("svc", login="twin-svc-assets", service=True)       # other services read
    assert (await client.post(f"{API}/types/batch-get", json={"ids": [one]}, headers=service)).status_code == 200
    assert (await client.post(f"{API}/types/{one}/archive", headers=service)).status_code == 403


async def test_a_set_and_a_type_with_it(client, app, tokens):
    admin = tokens.admin()
    category = (await named(client, admin, "categories"))["Медицинская техника"]["id"]
    r = await client.post(f"{API}/property-sets", headers=admin, json={"name": "Стерилизация", "properties": [
        prop("sterilized", "Дата стерилизации", "date", editable_by="responsible"),
        prop("method", "Метод", "choice", options=[{"value": "steam", "title": "пар"}], stored="type")]})
    assert r.status_code == 201
    sset = r.json()

    body = {"category_id": category, "name": "Эндоскоп", "w": 0.6, "d": 0.4, "h": 0.2, "portable": True,
            "sets": [sset["id"]], "properties": [prop("channels", "Число каналов", "number", stored="type")],
            "values": {"method": "steam", "channels": 2}}
    r = await client.post(f"{API}/types", json=body, headers=admin)
    assert r.status_code == 201
    made = r.json()
    assert [p["key"] for p in made["schema"]] == ["sterilized", "method", "channels"]
    assert made["schema_version"] == 1 and made["portable"] is True

    # what does not fit is refused
    bad = [({**body, "properties": [prop("method")]}, 409),                          # a key the set already has
           ({**body, "properties": [prop("a"), prop("a")]}, 422),                    # a key twice
           ({**body, "properties": [prop("Плохой ключ")]}, 422),
           ({**body, "properties": [prop("c", kind="choice")]}, 422),                # a choice of nothing
           ({**body, "values": {"method": "fire"}}, 422),                            # not one of the options
           ({**body, "values": {"sterilized": "2026-01-01"}}, 422),                  # kept with objects, not the type
           ({**body, "sets": [category]}, 422), ({**body, "w": 0}, 422), ({**body, "category_id": sset["id"]}, 422),
           ({**body, "wall_mounted": True, "ceiling_mounted": True}, 422)]                # on a wall or on the ceiling
    for wrong, status in bad:
        assert (await client.post(f"{API}/types", json=wrong, headers=admin)).status_code == status, wrong

    # the set changes: the schema of every type with it has a new version, and they are named in the event
    changed = {"name": "Стерилизация", "version": sset["version"], "properties": [
        *sset["properties"], prop("cycles", "Число циклов", "number", editable_by="responsible")]}
    assert (await client.patch(f"{API}/property-sets/{sset['id']}", json=changed, headers=admin)).status_code == 200
    again = (await client.get(f"{API}/types/{made['id']}", headers=admin)).json()
    assert again["schema_version"] == 2 and [p["key"] for p in again["schema"]][2] == "cycles"
    last = (await events(app))[-1]
    assert last["type"] == "catalog.property_set.changed" and last["data"]["type_ids"] == [made["id"]]
    stale = await client.patch(f"{API}/property-sets/{sset['id']}", json=changed, headers=admin)
    assert stale.status_code == 409
    # a property whose key a type already has cannot come into the set
    clash = {**changed, "version": sset["version"] + 1, "properties": [*changed["properties"], prop("channels")]}
    r = await client.patch(f"{API}/property-sets/{sset['id']}", json=clash, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "key_conflict"
    assert (await client.delete(f"{API}/property-sets/{sset['id']}", headers=admin)).json()["code"] == "in_use"

    # changing the type: only a change of the schema makes a new schema version
    patch = {**body, "name": "Эндоскоп гибкий", "version": again["version"]}
    renamed = (await client.patch(f"{API}/types/{made['id']}", json=patch, headers=admin)).json()
    assert (renamed["schema_version"], (await events(app))[-1]["data"]["schema_changed"]) == (2, False)
    patch = {**patch, "portable": False, "version": renamed["version"]}
    fixed = (await client.patch(f"{API}/types/{made['id']}", json=patch, headers=admin)).json()
    assert (fixed["schema_version"], (await events(app))[-1]["data"]["schema_changed"]) == (3, True)


async def test_archived_type_is_not_offered_but_opens(client, app, tokens):
    admin, user = tokens.admin(), tokens.bearer("user-1")
    chair = (await named(client, user, "types"))["Кресло посетителя"]
    assert (await client.post(f"{API}/types/{chair['id']}/archive", headers=admin)).json()["active"] is False
    assert "Кресло посетителя" not in await named(client, user, "types")
    assert "Кресло посетителя" in await named(client, user, "types?active=false")
    assert (await client.get(f"{API}/types/{chair['id']}", headers=user)).json()["name"] == "Кресло посетителя"
    batch = await client.post(f"{API}/types/batch-get", json={"ids": [chair["id"]]}, headers=user)
    assert len(batch.json()["items"]) == 1
    assert (await client.post(f"{API}/types/{chair['id']}/restore", headers=admin)).json()["active"] is True
    assert [e["type"] for e in await events(app)] == ["catalog.type.archived", "catalog.type.restored"]

    # a section with types in it cannot be removed
    r = await client.delete(f"{API}/categories/{chair['category_id']}", headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "in_use"


def glb(size: tuple[float, float, float]) -> bytes:
    """A GLB that only says how large its one mesh is."""
    doc = json.dumps({"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
                      "accessors": [{"min": [0, 0, 0], "max": list(size), "type": "VEC3", "componentType": 5126,
                                     "count": 3}]}).encode()
    doc += b" " * (-len(doc) % 4)
    return b"glTF" + struct.pack("<II", 2, 20 + len(doc)) + struct.pack("<II", len(doc), 0x4E4F534A) + doc


async def test_model_of_a_type(client, tokens):
    admin, user = tokens.admin(), tokens.bearer("user-1")
    couch = (await named(client, user, "types"))["Кушетка"]               # 1.9 × 0.65 × 0.55 m
    url = f"{API}/types/{couch['id']}/model"
    assert (await client.get(f"{url}.glb", headers=user)).status_code == 404
    assert (await client.put(url, files={"file": ("m.glb", b"not a model")}, headers=admin)).status_code == 422

    fits = glb((1.9, 0.55, 0.65))                                         # the same size, other axes
    r = await client.put(url, files={"file": ("Кушетка.glb", fits)}, headers=admin)
    assert r.status_code == 200 and r.json()["model"] == {
        "name": "Кушетка.glb", "size": len(fits), "rotation": 0, "bounds": [1.9, 0.55, 0.65], "warnings": []}
    assert (await client.get(f"{url}.glb", headers=user)).content == fits

    # drawn in millimetres: accepted, with a warning
    r = await client.put(url, files={"file": ("mm.glb", glb((1900, 550, 650)))}, headers=admin)
    assert r.status_code == 200 and "больше чем вдвое" in r.json()["model"]["warnings"][0]
    assert (await client.delete(url, headers=admin)).status_code == 204
    assert (await client.get(f"{API}/types/{couch['id']}", headers=user)).json()["model"] is None


async def test_property_with_values_at_objects_stays(client, tokens, used):
    admin = tokens.admin()
    couch = (await named(client, admin, "types"))["Кушетка"]
    sset = (await named(client, admin, "property-sets"))["Мебель"]             # material, wear — both kept with objects
    used["wear"] = 3                                 # three objects have their wear filled in

    without = {"name": sset["name"], "version": sset["version"], "properties": [sset["properties"][0]]}
    r = await client.patch(f"{API}/property-sets/{sset['id']}", json=without, headers=admin)
    assert r.status_code == 409 and r.json()["code"] == "in_use" and "Износ" in r.json()["detail"]
    as_text = {**sset["properties"][1], "kind": "text", "options": None}
    other_kind = {**without, "properties": [sset["properties"][0], as_text]}
    assert (await client.patch(f"{API}/property-sets/{sset['id']}", json=other_kind, headers=admin)).status_code == 409
    # the type cannot drop the set either
    body = {"category_id": couch["category_id"], "name": couch["name"], "w": 1.9, "d": 0.65, "h": 0.55,
            "sets": [couch["sets"][0]], "properties": couch["properties"], "values": couch["values"],
            "version": couch["version"]}
    assert (await client.patch(f"{API}/types/{couch['id']}", json=body, headers=admin)).status_code == 409
    # a property nobody has filled in goes freely; a new one comes freely
    used.clear()
    assert (await client.patch(f"{API}/property-sets/{sset['id']}", json=without, headers=admin)).status_code == 200


async def test_products_of_a_type(client, app, tokens):
    """A make and model of a type: offered with the type, priced by its list price; one of a kind per type."""
    admin, user = tokens.admin(), tokens.bearer("user-1")
    monitor = (await named(client, user, "types"))["Монитор 27″"]
    url = f"{API}/types/{monitor['id']}/products"
    dell = {"vendor": "Dell", "name": "P2723DE", "article": "210-BDDW", "supplier": "ООО «Сервер»", "price": 32990}
    r = await client.post(url, json=dell, headers=admin)
    assert r.status_code == 201
    made = r.json()
    assert (made["type_id"], made["vendor"], made["price"], made["active"]) == (monitor["id"], "Dell", 32990.0, True)
    assert (await events(app))[-1]["type"] == "catalog.product.created"
    # the same make and model twice is refused; the user reads, the administrator writes
    assert (await client.post(url, json={**dell, "name": " P2723DE "}, headers=admin)).status_code == 409
    assert (await client.post(url, json={"vendor": "LG", "name": "27UL550"}, headers=user)).status_code == 403
    assert (await client.post(url, json={"vendor": "LG", "name": "27UL550"}, headers=admin)).status_code == 201
    assert (await client.post(f"{API}/types/{made['id']}/products", json=dell, headers=admin)).status_code == 404
    # listed with the type, counted on it
    assert [p["vendor"] for p in (await client.get(url, headers=user)).json()["items"]] == ["Dell", "LG"]
    assert (await client.get(f"{API}/types/{monitor['id']}", headers=user)).json()["products"] == 2
    assert (await named(client, user, "types"))["Монитор 27″"]["products"] == 2
    # a change against a stale version is refused; archived — out of the type's offer, still read by id
    patch = {**dell, "price": 29990, "version": made["version"]}
    assert (await client.patch(f"{API}/products/{made['id']}", json=patch, headers=admin)).json()["price"] == 29990.0
    assert (await client.patch(f"{API}/products/{made['id']}", json=patch, headers=admin)).status_code == 409
    gone = await client.post(f"{API}/products/{made['id']}/archive", headers=admin)
    assert gone.json()["active"] is False and (await events(app))[-1]["type"] == "catalog.product.archived"
    assert [p["vendor"] for p in (await client.get(url, headers=user)).json()["items"]] == ["LG"]
    assert (await client.get(f"{API}/products/{made['id']}", headers=user)).json()["name"] == "P2723DE"
    assert len((await client.get(f"{API}/products?type_id={monitor['id']}", headers=user)).json()["items"]) == 2
    # the office set no longer keeps a vendor and a model with the type
    office = (await named(client, user, "property-sets"))["Оргтехника"]
    assert [p["key"] for p in office["properties"]][:1] == ["consumables"]
