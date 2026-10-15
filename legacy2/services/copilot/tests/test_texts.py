# ruff: noqa: E501
"""Facts for texts — the passport, the digest, a revision — and a plan drawn from a description."""
from __future__ import annotations

import json

from conftest import API, BUILDING, NEW_SKETCH, configure
from test_chat import UI, ask, new_chat


def told(model, n: int = 1) -> list[dict]:
    return [json.loads(m["content"]) for m in model.requests[n]["body"]["messages"] if m["role"] == "tool"]


async def test_passport_digest_and_revision(app, client, tokens, world, model):
    await configure(client, tokens)
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [{"calls": [("building_passport", {}), ("journal_digest", {"days": 3}), ("revisions", {}), ("revision", {"revision_id": "rev-1"})]}, {"text": "Паспорт готов."}]
    got = await ask(client, me, chat, "опиши здание, что произошло за 3 дня и что в ревизии")
    assert all("error" not in e for e in got if e["type"] == "tool")
    passport, digest, revs, rev = told(model)
    assert passport["building"]["name"] == "Корпус А" and passport["rooms_total"] == 2 and passport["area_total"] == 30.4
    assert passport["rooms_by_type"] == {"office": 1, "technical": 1} and passport["assets_total"] == 2
    assert passport["assets_by_state"] == {"in_use": 1, "faulty": 1} and passport["without_responsible"] == 1
    assert passport["top_responsible"] == [{"person": "Петров П. П.", "assets": 1}]
    assert digest["events"] == 3 and digest["became_faulty"] == 1 and digest["moved"] == 1
    assert [n["what"] for n in digest["notable"]] == ["смена состояния", "перемещение"]
    assert digest["active"][0]["events"] == 2 and world.asked_journal["building_id"] == BUILDING and world.asked_journal["from"].startswith("20")
    assert revs["revisions"][0]["status"] == "draft"
    assert rev["differences"]["counts"] == {"new": 1, "same": 1, "retired": 1} and "Подвал" in rev["warnings"][0]


async def test_a_plan_from_words_is_a_proposal_of_a_new_drawing(app, client, tokens, world, model):
    await configure(client, tokens)
    world.admins.add("user-1")
    me = tokens.bearer("user-1")
    chat = await new_chat(client, me)
    model.script = [
        {"calls": [("draw_plan", {"template": "corridor", "params": {"rooms_top": 2, "rooms_bottom": 2, "corridor_width": 2.4}, "then": "return"})]},
        {"calls": [("draw_plan", {"template": "corridor", "params": {"rooms_top": 2, "rooms_bottom": 2}, "name": "Второй этаж"})]},
        {"text": "Предложил план."},
    ]
    got = await ask(client, me, chat, "нарисуй коридор с четырьмя кабинетами")
    shown = told(model)[0]
    assert shown["made"]["rooms"] == 4 and len(shown["rooms"]) == 4 and "proposal" not in shown
    prop = next(e["proposal"] for e in got if e["type"] == "proposal")
    assert prop["status"] == "open" and "Второй этаж" in prop["labels"][0] and world.templates[0]["params"]["corridor_width"] == 2.4
    # nothing drawn yet; applied, the drawing is made and the plan put into it, and the proposal names the drawing
    assert world.new_sketches == []
    r = await client.post(f"{API}/proposals/{prop['id']}/apply", headers=me)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    assert r.json()["drawing_id"] == NEW_SKETCH and r.json()["result"]["done"][0]["drawing_id"] == NEW_SKETCH
    assert world.new_sketches == [{"building_id": BUILDING, "name": "Второй этаж"}]
    assert world.new_sketch_body == {"sketch": {"version": 1, "floors": [{"id": "f1", "template": "corridor"}]}, "version": 1}
    # the words the template refuses come back to the model as an error
    model.script = [{"calls": [("draw_plan", {"template": "corridor", "params": {"rooms": "много"}})]}, {"text": "."}]
    got = await ask(client, me, chat, "нарисуй много", ui=UI)
    assert "число помещений" in next(e["error"] for e in got if e["type"] == "tool")
