# ruff: noqa: E501
"""Proposals: made by a tool, applied or rejected by an administrator of the building with their own token,
stale when the data changed; variants for objects; who may propose; the audit."""
from __future__ import annotations

from conftest import API, BUILDING, FLOOR, MONITOR, PETROV, PRINTER, ROOM214, ROOM215, configure
from test_chat import ask, new_chat


async def test_rooms_proposal_is_applied_by_the_user(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("propose_rooms", {"summary": "Переименовать 214 в приёмную", "changes": [{"room_id": ROOM214, "name": "Приёмная"}]})]},
        {"text": "Предложил переименовать."},
    ]
    got = await ask(client, me, chat, "переименуй 214 в приёмную")
    assert got[0]["mode"] == "propose"
    assert [e["name"] for e in got if e["type"] == "tool"] == ["propose_rooms"]
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert prop["status"] == "open" and prop["count"] == 1 and "Приёмная" in prop["labels"][0]
    # told to the model: it must not claim the change is made
    assert "применит он сам" in model.requests[1]["body"]["messages"][-1]["content"]
    # nothing changed yet
    assert world.rooms[ROOM214]["name"] == "Кабинет"
    # the proposal is in the chat, in the list, and readable with its actions
    items = (await client.get(f"{API}/chats/{chat}", headers=me)).json()["items"]
    assert [i["type"] for i in items] == ["user", "tool", "proposal", "assistant"]
    assert (await client.get(f"{API}/proposals", headers=me, params={"building_id": BUILDING})).json()["items"][0]["id"] == prop["id"]
    full = (await client.get(f"{API}/proposals/{prop['id']}", headers=me)).json()
    assert full["actions"][0]["method"] == "PATCH" and full["actions"][0]["body"] == {"name": "Приёмная", "version": 1}
    # applied: the room is renamed by the user's own token, the proposal remembers it
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied" and r.json()["result"]["done"][0]["status"] == 200
    assert world.rooms[ROOM214]["name"] == "Приёмная"
    assert ("user-1", "PATCH", f"/api/buildings/v1/rooms/{ROOM214}") in world.asked
    # not twice
    assert (await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)).status_code == 409


async def test_stale_and_rejected(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("propose_state", {"summary": "Принтер в ремонт", "changes": [{"asset_id": PRINTER, "state": "repair"}]}),
                   ("propose_responsible", {"summary": "Петров за принтер", "changes": [{"asset_id": PRINTER, "person_id": PETROV}]})]},
        {"text": "Два предложения."},
    ]
    got = await ask(client, me, chat, "принтер в ремонт и назначь Петрова")
    first, second = [e["proposal"] for e in got if e["type"] == "proposal"]
    # someone changes the printer meanwhile: the first proposal is stale
    world.assets[PRINTER]["version"] += 1
    r = await client.post(f"{API}/proposals/{first['id']}/apply", headers=me)
    assert r.status_code == 200 and r.json()["status"] == "stale"
    assert r.json()["result"]["failed"]["status"] == 409
    assert world.assets[PRINTER]["state"] == "faulty"
    # the second is rejected with a reason the copilot can read later
    r = await client.post(f"{API}/proposals/{second['id']}/reject", headers=me, json={"reason": "Петров в отпуске"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["result"]["reason"] == "Петров в отпуске"
    assert (await client.post(f"{API}/proposals/{second['id']}/reject", headers=me, json={})).status_code == 409


async def test_who_may_propose_and_decide(app, client, tokens, world, model):
    await configure(client, tokens)
    me, boss = tokens.bearer("user-1"), tokens.bearer("user-2")
    world.admins.add("user-2")
    chat = await new_chat(client, me)
    # a reader is offered no proposing tools, and cannot call them
    model.script = [{"calls": [("propose_rooms", {"summary": "x", "changes": [{"room_id": ROOM214, "name": "Y"}]})]}, {"text": "Нельзя."}]
    got = await ask(client, me, chat, "переименуй")
    assert got[0]["mode"] == "read"
    assert "Нет инструмента" in next(e["error"] for e in got if e["type"] == "tool")
    offered = {t["function"]["name"] for t in model.requests[0]["body"]["tools"]}
    assert "propose_rooms" not in offered and "find_rooms" in offered
    # an administrator proposes; the reader sees only their own proposals and may not decide
    chat2 = await new_chat(client, boss)
    model.script = [{"calls": [("propose_comment", {"target_kind": "room", "target_id": ROOM214, "body": "Проверить розетки"})]}, {"text": "Ок"}]
    got = await ask(client, boss, chat2, "оставь замечание")
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert (await client.get(f"{API}/proposals/{prop['id']}", headers=me)).status_code == 404
    assert (await client.get(f"{API}/proposals", headers=me, params={"building_id": BUILDING})).json()["items"] == []
    assert (await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)).status_code == 404
    # the system administrator sees and may apply
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=tokens.admin())
    assert r.status_code == 200 and r.json()["status"] == "applied"
    assert world.comments[0]["body"] == "Проверить розетки" and world.comments[0]["target_id"] == ROOM214


async def test_objects_are_proposed_and_moved_on_approval(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("room", {"room_id": ROOM214})]},
        {"calls": [("move_to_room", {"asset_ids": [MONITOR, PRINTER], "room_id": ROOM215})]},
        {"text": "Предложил перенос."},
    ]
    got = await ask(client, me, chat, "перенеси всё из 214 в 215")
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert prop["status"] == "open" and prop["count"] == 2 and "Перенести 2 объектов в 215 Серверная" == prop["summary"]
    # drawn on the plan: where each goes and where it stands now
    shows = prop["shows"]
    assert [s["kind"] for s in shows] == ["move", "move"] and shows[0]["from"] == {"floor_id": FLOOR, "x": 2.5, "y": 1.0}
    pts = {(s["x"], s["y"]) for s in shows}
    assert len(pts) == 2 and all(0 < x < 4 and 0.5 <= y < 3 for x, y in pts)
    # the places were checked against the plan (the stand-in's door is at y < 0.5: anything there is moved up)
    assert world.rules and world.rules[-1][0] == "layout-check" and len(world.rules[-1][1]["moves"]) == 2
    # the fact is untouched until approved; then the objects are moved with the user's token
    assert world.assets[MONITOR]["x"] == 2.5
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    assert world.assets[MONITOR]["floor_id"] == FLOOR and (world.assets[MONITOR]["x"], world.assets[MONITOR]["y"]) in pts
    assert ("user-1", "POST", f"/api/assets/v1/assets/{PRINTER}/move") in world.asked
    # an empty proposal is refused
    model.script = [{"calls": [("propose_objects", {"summary": "ничего"})]}, {"text": "."}]
    got = await ask(client, me, chat, "сделай пустое")
    assert "пуст" in next(e["error"] for e in got if e["type"] == "tool")


async def test_new_objects_get_numbers_when_applied(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("propose_objects", {"summary": "Два стола", "places": [{"type_id": "t-desk", "floor_id": FLOOR, "x": 1, "y": 1},
                                                                                        {"type_id": "t-desk", "floor_id": FLOOR, "x": 3, "y": 1, "inventory_no": "СТ-7"}],
                                                    "removes": [PRINTER]})]}, {"text": "."}]
    got = await ask(client, me, chat, "поставь два стола и спиши принтер")
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert [s["kind"] for s in prop["shows"]] == ["remove", "new", "new"] and "Поставить Стол СТ-7" in prop["labels"][2]
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.json()["status"] == "applied", r.text
    done = r.json()["result"]["done"]
    assert done[1]["inventory_no"].startswith("ИЗ-") and done[2]["inventory_no"] == "СТ-7" and done[1]["asset_id"]
    assert world.assets[PRINTER]["state"] == "retired" and sum(1 for a in world.assets.values() if a.get("type_id") == "t-desk") == 2


async def test_a_crashing_tool_is_told_not_fatal(app, client, tokens, world, model, monkeypatch):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    world.rooms[ROOM215]["polygon"] = "garbage"
    model.script = [{"calls": [("move_to_room", {"asset_ids": [MONITOR], "room_id": ROOM215})]}, {"text": "Не вышло, скажу словами."}]
    got = await ask(client, me, chat, "перенеси монитор в 215")
    tool = next(e for e in got if e["type"] == "tool")
    assert "error" in tool and got[-1]["type"] == "done"
    assert "".join(e.get("text", "") for e in got if e["type"] == "text") == "Не вышло, скажу словами."


async def test_assignments_and_grants(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("propose_assignments", {"summary": "Петров в 215", "assign": [{"person_id": PETROV, "room_id": ROOM215}], "unassign": [{"person_id": PETROV, "room_id": ROOM214}]}),
                   ("propose_grants", {"summary": "Петров — ответственный за 215", "grant": [{"person_id": PETROV, "role": "responsible", "scope_kind": "room", "scope_id": ROOM215}]})]},
        {"text": "Готово."},
    ]
    got = await ask(client, me, chat, "переведи Петрова в 215")
    a, g = [e["proposal"] for e in got if e["type"] == "proposal"]
    assert a["count"] == 2 and "Петров П. П. → 215 Серверная" in a["labels"][0]
    for p in (a, g):
        assert (await client.post(f"{API}/proposals/{p['id']}/apply", headers=me)).json()["status"] == "applied"
    assert world.assignments == [(PETROV, ROOM215)]
    assert world.grants[0]["scope"] == {"kind": "room", "id": ROOM215} and world.grants[0]["building_id"] == BUILDING


async def test_audit(app, client, tokens, world, model):
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("audit_assets", {"days": 10})]}, {"text": "Вот."}]
    got = await ask(client, me, chat, "проверь учёт")
    assert "error" not in next(e for e in got if e["type"] == "tool")
    import json
    data = json.loads(model.requests[1]["body"]["messages"][-1]["content"])
    assert data["scanned"] == 2
    assert data["counts"] == {"no_responsible": 1, "needs_placement": 0, "needs_fill": 0, "faulty": 1, "repair": 0,
                              "expired": 0, "expiring": 1, "stale": 1}
    assert data["lists"]["expiring"][0]["prop"] == "warranty_until" and data["lists"]["expiring"][0]["room"] == "214 Кабинет"
    assert data["lists"]["no_responsible"][0]["inventory_no"] == "00124"
    assert data["lists"]["stale"][0]["inventory_no"] == "00124"
