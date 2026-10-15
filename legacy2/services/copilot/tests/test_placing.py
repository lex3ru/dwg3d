# ruff: noqa: E501
"""Placing by rules through the copilot: the planning service counts the places, the copilot makes a variant of them."""
from __future__ import annotations

import json

from conftest import API, BUILDING, FLOOR, MONITOR, ROOM214, ROOM215, configure
from test_chat import ask, new_chat

UI = {"section": "plan", "building": {"id": BUILDING, "name": "Корпус А"}, "floor": {"id": FLOOR, "name": "2 этаж"}}


async def test_detectors_become_a_variant(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("place_detectors", {"floor_id": FLOOR})]}, {"text": "Предложил вариант с извещателями."}]
    got = await ask(client, me, chat, "поставь извещатели на этаже", ui=UI)
    assert [e for e in got if e["type"] == "tool"] == [{"type": "tool", "name": "place_detectors"}]
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert prop["status"] == "open" and prop["count"] == 2 and prop["summary"].startswith("Добавить 2 × Извещатель")
    kind, body = world.rules[0]
    assert kind == "detectors" and body["type_id"] == "t-smoke" and body["floor_id"] == FLOOR
    assert [s["x"] for s in prop["shows"]] == [1, 2] and all(s["kind"] == "new" for s in prop["shows"])
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.json()["status"] == "applied" and sum(1 for a in world.assets.values() if a.get("type_id") == "t-smoke") == 2
    told = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][-1])
    assert told["to_add"] == 2 and told["rooms"][0]["need"] == 2 and "применит он сам" in told["next"]


async def test_places_shown_or_proposed(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("place_by_rules", {"type_id": "t-desk", "room_ids": [ROOM214], "count": 2, "then": "return"})]},
        {"calls": [("place_by_rules", {"type_id": "t-desk", "room_ids": [ROOM214], "count": 2, "where": "grid", "summary": "Столы в 214"})]},
        {"text": "Готово."},
    ]
    got = await ask(client, me, chat, "расставь столы в 214", ui=UI)
    props = [e["proposal"] for e in got if e["type"] == "proposal"]
    assert len(props) == 1 and props[0]["summary"] == "Столы в 214"
    shown = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][-1])
    assert shown["placed"] == 2 and len(shown["places"]) == 2 and "proposal" not in shown
    assert world.rules[1][1]["where"] == "grid"


async def test_checks_and_rights(app, client, tokens, world, model):
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("check_placement", {}), ("coverage", {}), ("place_by_rules", {"type_id": "t-desk", "floor_id": FLOOR})]}, {"text": "."}]
    got = await ask(client, me, chat, "что не так на этаже?", ui=UI)
    tools = [e for e in got if e["type"] == "tool"]
    assert "error" not in tools[0] and "error" not in tools[1] and "Нет инструмента" in tools[2]["error"]
    told = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][0])
    assert told["counts"]["blocked"] == 1 and "мешает двери" in told["blocked"][0]["problems"][0]
    # without a floor on screen the tool says what it needs
    model.script = [{"calls": [("check_placement", {})]}, {"text": "."}]
    got = await ask(client, me, chat, "проверь", ui={"building": {"id": BUILDING, "name": "Корпус А"}})
    assert "Не задан этаж" in next(e["error"] for e in got if e["type"] == "tool")


async def test_room_geometry_and_front_of(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("room_geometry", {"room_id": ROOM215}),
                               ("place_by_rules", {"type_id": "t-desk", "where": "front_of"}),
                               ("place_by_rules", {"type_id": "t-desk", "where": "front_of", "anchor_asset_id": MONITOR, "count": 2, "then": "return"})]},
                    {"text": "."}]
    got = await ask(client, me, chat, "как устроена серверная?", ui=UI)
    tools = [e for e in got if e["type"] == "tool"]
    assert "error" not in tools[0] and "anchor_asset_id" in tools[1]["error"] and "error" not in tools[2]
    geo = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][0])
    assert geo["size"] == [4.0, 3.0] and len(geo["walls"]) == 4
    by_side = {w["side"]: w for w in geo["walls"]}
    assert by_side["south"]["openings"][0]["kind"] == "door" and by_side["north"]["openings"][0]["kind"] == "window"
    assert by_side["west"]["free"] and by_side["east"]["free"] and by_side["west"]["side_name"] == "запад (левая)"
    assert world.rules[-1][1]["anchor_asset_id"] == MONITOR and world.rules[-1][1]["where"] == "front_of"


async def test_exact_places_at_a_wall_and_at_a_point(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("place_at", {"type_id": "t-desk", "room_id": ROOM214, "wall": {"side": "west", "along": 1.0}, "count": 2, "summary": "Два стола у западной стены"}),
                               # a model that writes nested objects as JSON text is understood all the same
                               ("place_at", {"type_id": "t-desk", "room_id": ROOM214, "point": '{"x": 2, "y": 0.2, "angle": 0}'}),
                               ("place_at", {"type_id": "t-desk", "room_id": ROOM214})]},
                    {"text": "Готово."}]
    got = await ask(client, me, chat, "стол к западной стене в метре от угла и ещё один у двери", ui=UI)
    tools = [e for e in got if e["type"] == "tool"]
    assert "error" not in tools[0] and "error" not in tools[1] and "одно: wall" in tools[2]["error"]
    props = [e["proposal"] for e in got if e["type"] == "proposal"]
    assert len(props) == 2 and props[0]["summary"] == "Два стола у западной стены" and props[0]["count"] == 2
    # the point in the doorway: the place is moved and the summary says why
    assert "мешает двери" in props[1]["summary"] and props[1]["shows"][0]["y"] == 0.6
    kinds = [k for k, _ in world.rules]
    assert kinds == ["placements", "placements"] and world.rules[0][1]["where"] == "at_wall" and world.rules[0][1]["along"] == 1.0 and world.rules[1][1]["where"] == "at_point"
    told = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][1])
    assert told["placed"] == 1 and "ближайшее свободное место" in told["notes"][0]


async def test_the_layout_is_checked_before_a_proposal(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("check_layout", {"places": [{"type_id": "t-desk", "x": 2, "y": 0.2}, {"type_id": "t-desk", "x": 2, "y": 2}]})]},
        # the model proposes with a desk still in the doorway: refused, told where it is free
        {"calls": [("propose_objects", {"summary": "Столы", "places": [{"type_id": "t-desk", "floor_id": FLOOR, "x": 2, "y": 0.2}, {"type_id": "t-desk", "floor_id": FLOOR, "x": 2, "y": 2}]})]},
        # corrected: goes through, with what the check saw
        {"calls": [("propose_objects", {"summary": "Столы", "places": [{"type_id": "t-desk", "floor_id": FLOOR, "x": 2, "y": 0.6}, {"type_id": "t-desk", "floor_id": FLOOR, "x": 2, "y": 2}],
                                        "moves": [{"asset_id": MONITOR, "x": 3, "y": 2}]})]},
        {"text": "Готово."},
    ]
    got = await ask(client, me, chat, "поставь два стола в 214", ui=UI)
    tools = [e for e in got if e["type"] == "tool"]
    assert tools[0]["name"] == "check_layout" and "error" not in tools[0]
    assert "так ставить нельзя" in tools[1]["error"] and "мешает двери" in tools[1]["error"] and "свободно рядом: (2.0, 0.6)" in tools[1]["error"]
    assert "error" not in tools[2]
    props = [e["proposal"] for e in got if e["type"] == "proposal"]
    assert len(props) == 1 and props[0]["count"] == 3
    checked = [b for k, b in world.rules if k == "layout-check"]
    assert len(checked) == 3 and checked[0]["floor_id"] == FLOOR and len(checked[2]["places"]) == 2 and checked[2]["moves"][0]["asset_id"] == MONITOR
    seen = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][0])
    assert seen["ok"] is False and seen["items"][0]["fix"] == [2, 0.6]
    told = json.loads([m["content"] for m in model.requests[3]["body"]["messages"] if m["role"] == "tool"][-1])
    assert told["check"]["ok"] is True and told["check"]["items"][0]["room"]["name"] == "Кабинет"
