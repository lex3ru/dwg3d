"""A question answered: the loop with tools, the user's token behind every request, the screen context,
the chat kept, limits, refusals passed on, who may talk to the copilot."""
from __future__ import annotations

import httpx
from conftest import API, BUILDING, FLOOR, LATER, MONITOR, OTHER_BUILDING, ROOM214, configure, events

UI = {"section": "rooms", "building": {"id": BUILDING, "name": "Корпус А"}, "floor": {"id": FLOOR, "name": "2 этаж"}}


async def ask(client, headers, chat_id, text, ui=UI):
    return events(await client.post(f"{API}/chats/{chat_id}/messages", headers=headers, json={"text": text, "ui": ui}))


async def new_chat(client, headers) -> str:
    r = await client.post(f"{API}/chats", headers=headers, json={"building_id": BUILDING})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_a_question_answered_with_tools(client, tokens, world, model):
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"reasoning": 2, "calls": [("find_rooms", {"q": "214"})]},
        {"calls": [("room", {"room_id": ROOM214})]},
        {"text": f"В [Кабинете 214](room:{ROOM214}) ТО в октябре требует [Монитор 00123](asset:{MONITOR})."},
    ]
    got = await ask(client, me, chat, "какое оборудование в кабинете 214 требует ТО в этом месяце")
    kinds = [e["type"] for e in got]
    assert kinds[0] == "chat" and got[0]["id"] == chat and got[0]["mode"] == "read"
    assert kinds.count("thinking") >= 1
    assert [e["name"] for e in got if e["type"] == "tool"] == ["find_rooms", "room"]
    assert "error" not in [k for e in got if e["type"] == "tool" for k in e]
    assert kinds[-1] == "done"

    # what the model saw: the system prompt, the screen context in the user's message, the tools, the results
    first = model.requests[0]["body"]
    assert first["messages"][0]["role"] == "system" and "Копилот" in first["messages"][0]["content"]
    assert "права только на просмотр" in first["messages"][0]["content"]
    assert first["messages"][1]["role"] == "user"
    assert "Сейчас у пользователя открыто" in first["messages"][1]["content"]
    assert "Корпус А" in first["messages"][1]["content"] and "2 этаж" in first["messages"][1]["content"]
    assert first["messages"][1]["content"].endswith("какое оборудование в кабинете 214 требует ТО в этом месяце")
    names = {t["function"]["name"] for t in first["tools"]}
    assert {"find_rooms", "room", "find_assets", "asset", "show", "report_link"} <= names
    third = model.requests[2]["body"]["messages"]
    assert third[-1]["role"] == "tool" and "00123" in third[-1]["content"] and "Петров" in third[-1]["content"]
    assert third[-3]["role"] == "tool" and "214" in third[-3]["content"]

    # every request to the other services carried the user's own token
    assert world.asked and {sub for sub, *_ in world.asked} == {"user-1"}

    # the chat is kept and shown
    full = (await client.get(f"{API}/chats/{chat}", headers=me)).json()
    kinds = [i["type"] for i in full["items"]]
    assert kinds == ["user", "tool", "tool", "assistant"]
    assert full["items"][0]["text"] == "какое оборудование в кабинете 214 требует ТО в этом месяце"
    assert "Монитор 00123" in full["items"][-1]["text"]
    chats = (await client.get(f"{API}/chats", headers=me, params={"building_id": BUILDING})).json()["items"]
    assert [c["id"] for c in chats] == [chat]

    # usage: three requests to the model
    assert (await client.get(f"{API}/status", headers=me)).json()["used_today"] == 3

    # the next message continues the conversation: the model sees the earlier turns
    model.script = [{"text": "Один объект."}]
    await ask(client, me, chat, "сколько их?")
    seen = model.requests[-1]["body"]["messages"]
    assert [m["role"] for m in seen][:2] == ["system", "user"] and seen[-1]["content"].endswith("сколько их?")
    assert sum(1 for m in seen if m["role"] == "user") == 2


async def test_property_filters_and_show(client, tokens, world, model):
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("find_assets", {"props": {"service_due.lte": LATER}, "room_id": ROOM214})]},
        {"calls": [("show", {"what": "asset", "id": MONITOR, "label": "Монитор 00123"})]},
        {"text": "Показал монитор."},
    ]
    got = await ask(client, me, chat, "покажи, у чего ТО до конца месяца")
    ui = [e for e in got if e["type"] == "ui"]
    assert ui == [{"type": "ui", "href": f"#/b/{BUILDING}/assets/{MONITOR}", "label": "Монитор 00123"}]
    result = model.requests[1]["body"]["messages"][-1]["content"]
    assert "00123" in result and "00124" not in result and '"room": "214 Кабинет"' in result
    # the ui command is part of the kept chat
    items = (await client.get(f"{API}/chats/{chat}", headers=me)).json()["items"]
    assert any(i["type"] == "ui" for i in items)


async def test_refusals_reach_the_model_not_the_data(client, tokens, world, model):
    """What the user may not see, the services refuse; the copilot passes the refusal on, invents nothing."""
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("find_rooms", {"q": "1", "building_id": OTHER_BUILDING}), ("asset", {"asset_id": "nope"}),
                   ("no_such_tool", {}), ("room", "{not json")]},
        {"text": "Этого вам не видно."},
    ]
    got = await ask(client, me, chat, "что в чужом здании?")
    errors = [e for e in got if e["type"] == "tool"]
    assert [e["name"] for e in errors] == ["find_rooms", "asset", "no_such_tool", "room"]
    assert all("error" in e for e in errors)
    assert "Не найдено или недоступно" in errors[0]["error"] and "Здание не найдено" in errors[0]["error"]
    assert "Нет инструмента" in errors[2]["error"] and "не JSON" in errors[3]["error"]
    told = [m["content"] for m in model.requests[1]["body"]["messages"] if m["role"] == "tool"]
    assert len(told) == 4 and "Объект не найден" in told[1]


async def test_who_may_talk(client, tokens, world, model):
    me, other = tokens.bearer("user-1"), tokens.bearer("user-2")
    # not configured: the chat may be made, a message is refused with a clear code
    chat = await new_chat(client, me)
    r = await client.post(f"{API}/chats/{chat}/messages", headers=me, json={"text": "эй"})
    assert r.status_code == 409 and r.json()["code"] == "not_configured"
    await configure(client, tokens, daily_limit=1)
    # someone else's chat does not exist for me
    assert (await client.get(f"{API}/chats/{chat}", headers=other)).status_code == 404
    assert (await client.post(f"{API}/chats/{chat}/messages", headers=other, json={"text": "эй"})).status_code == 404
    assert (await client.delete(f"{API}/chats/{chat}", headers=other)).status_code == 404
    # a guest has no copilot at all
    guest = tokens.guest("floor", FLOOR, BUILDING, FLOOR)
    assert (await client.post(f"{API}/chats", headers=guest, json={})).status_code == 403
    # the daily limit
    model.script = [{"text": "Привет"}]
    assert [e["type"] for e in await ask(client, me, chat, "привет")][-1] == "done"
    r = await client.post(f"{API}/chats/{chat}/messages", headers=me, json={"text": "ещё"})
    assert r.status_code == 429 and r.json()["code"] == "daily_limit"
    # an administrator of the building may propose
    world.admins.add("user-2")
    chat2 = await new_chat(client, other)
    model.script = [{"text": "Да"}]
    got = await ask(client, other, chat2, "ты можешь предлагать?")
    assert got[0]["mode"] == "propose"
    assert "Предлагающие инструменты доступны" in model.requests[-1]["body"]["messages"][0]["content"]
    # deleting removes the chat and its messages
    assert (await client.delete(f"{API}/chats/{chat}", headers=me)).status_code == 204
    assert (await client.get(f"{API}/chats/{chat}", headers=me)).status_code == 404


async def test_model_failures_are_told_and_kept(client, tokens, world, model):
    await configure(client, tokens, max_steps=2)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [httpx.Response(500, text="boom")]
    got = await ask(client, me, chat, "привет")
    assert got[-1]["type"] == "error" and "500" in got[-1]["message"]
    items = (await client.get(f"{API}/chats/{chat}", headers=me)).json()["items"]
    assert [i["type"] for i in items] == ["user", "error"]
    # too many steps: the loop stops and says so
    model.script = [{"calls": [("buildings", {})]}, {"calls": [("buildings", {})]}, {"text": "never"}]
    got = await ask(client, me, chat, "крути")
    assert "слишком много шагов" in "".join(e.get("text", "") for e in got if e["type"] == "text")
    assert got[-1]["type"] == "done"
    # a server that answers without a stream is understood too
    model.script = [httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Целиком"}}]})]
    got = await ask(client, me, chat, "без потока")
    assert "".join(e.get("text", "") for e in got if e["type"] == "text") == "Целиком"
