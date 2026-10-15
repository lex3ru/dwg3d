# ruff: noqa: E501
"""The drawn plan through the copilot: its issues, the repair as a proposal, applied by the editor or by the service."""
from __future__ import annotations

import json

from conftest import API, BUILDING, FILE_DRAWING, SKETCH, configure
from test_chat import ask, new_chat

UI = {"section": "рисование плана", "building": {"id": BUILDING, "name": "Корпус А"}, "drawing": {"id": SKETCH, "name": "План"}}


async def test_issues_and_repair_as_a_proposal(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("check_plan", {})]},
        {"calls": [("propose_plan_fixes", {"summary": "Починить план"})]},
        {"text": "Нашёл ошибку и предложил починку."},
    ]
    got = await ask(client, me, chat, "проверь план и исправь, что можно", ui=UI)
    told = [m["content"] for m in model.requests[2]["body"]["messages"] if m["role"] == "tool"]
    issues = json.loads(told[0])
    assert issues["drawing_id"] == SKETCH and issues["by_code"] == {"short-wall": 1, "unnamed-room": 1} and issues["fixable"] == ["short-wall"]
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert prop["sketch"] == {"drawing_id": SKETCH, "version": 3} and prop["count"] == 1 and "стена s убрана" in prop["labels"][0]
    assert world.repairs == [{"codes": None, "floor_id": None}]
    # nothing saved yet; the proposal carries the repaired plan
    assert world.sketch_version == 3
    full = (await client.get(f"{API}/proposals/{prop['id']}", headers=me)).json()
    assert full["actions"][0]["kind"] == "sketch" and full["actions"][0]["sketch"]["floors"][0]["fixed"] is True
    # applied by the service: the plan is put with the version it was repaired from
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    assert world.sketch_version == 4 and world.sketch["floors"][0]["fixed"] is True


async def test_the_editor_applies_the_plan_itself(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("propose_plan_fixes", {"drawing_id": SKETCH})]}, {"text": "Готово."}]
    got = await ask(client, me, chat, "почини план", ui=UI)
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me, params={"by": "editor"})
    assert r.status_code == 200 and r.json()["status"] == "applied" and r.json()["result"]["done"][0]["status"] == "editor"
    assert world.sketch_version == 3                       # the service put nothing: the editor saves
    # someone saved the plan meanwhile: the service's apply of another proposal goes stale
    model.script = [{"calls": [("propose_plan_fixes", {})]}, {"text": "Ещё."}]
    got = await ask(client, me, chat, "ещё раз", ui=UI)
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    world.sketch_version += 1
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.json()["status"] == "stale"
    # a proposal that is not a plan cannot be marked applied by the editor
    assert (await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me, params={"by": "editor"})).status_code == 409


async def test_summary_and_no_drawing(app, client, tokens, world, model):
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("plan_summary", {}), ("drawings", {}), ("plan_summary", {"drawing_id": SKETCH})]}, {"text": "."}]
    got = await ask(client, me, chat, "что нарисовано?")
    tools = [e for e in got if e["type"] == "tool"]
    assert "Не задан чертёж" in tools[0]["error"] and "error" not in tools[1] and "error" not in tools[2]
    told = [m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"]
    assert json.loads(told[1])["drawings"][0]["kind"] == "sketch"
    assert json.loads(told[2])["floors"][0]["unnamed"] == 1
    # a drawing uploaded from a file has no drawn plan to check: the model is told where to look instead
    model.script = [{"calls": [("check_plan", {})]}, {"text": "."}]
    got = await ask(client, me, chat, "проверь план", ui={"building": {"id": BUILDING, "name": "Корпус А"}, "drawing": {"id": FILE_DRAWING}})
    assert "загружен из файла" in next(e["error"] for e in got if e["type"] == "tool")
    # a reader cannot propose the repair
    model.script = [{"calls": [("propose_plan_fixes", {"drawing_id": SKETCH})]}, {"text": "."}]
    got = await ask(client, me, chat, "почини")
    assert "Нет инструмента" in next(e["error"] for e in got if e["type"] == "tool")
