# ruff: noqa: E501
"""Placing by rules through the copilot: the planning service counts the places, the copilot makes a variant of them."""
from __future__ import annotations

import json

from conftest import BUILDING, FLOOR, ROOM214, configure
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
    assert prop["kind"] == "variant" and prop["name"] == "Извещатели: +2" and prop["counts"]["add"] == 2
    kind, body = world.rules[0]
    assert kind == "detectors" and body["type_id"] == "t-smoke" and body["floor_id"] == FLOOR
    ops = world.variants[prop["variant_id"]]["ops"]
    assert [o["data"]["x"] for o in ops] == [1, 2] and all(o["data"]["type_id"] == "t-smoke" for o in ops)
    told = json.loads([m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"][-1])
    assert told["to_add"] == 2 and told["rooms"][0]["need"] == 2 and "применит сам" in told["next"]


async def test_places_shown_or_proposed(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("place_by_rules", {"type_id": "t-desk", "room_ids": [ROOM214], "count": 2, "then": "return"})]},
        {"calls": [("place_by_rules", {"type_id": "t-desk", "room_ids": [ROOM214], "count": 2, "where": "grid", "name": "Столы в 214"})]},
        {"text": "Готово."},
    ]
    got = await ask(client, me, chat, "расставь столы в 214", ui=UI)
    props = [e["proposal"] for e in got if e["type"] == "proposal"]
    assert len(props) == 1 and props[0]["name"] == "Столы в 214"
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
