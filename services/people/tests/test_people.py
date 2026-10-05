"""The directory, linking accounts, the Excel import."""
from __future__ import annotations

import io

from openpyxl import Workbook
from sqlalchemy import select
from twin_chassis.db import outbox

from .conftest import API


async def events(app) -> list[dict]:
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        return [e for (e,) in rows]


async def add(client, headers, **fields) -> dict:
    r = await client.post(f"{API}/people", json={"full_name": "Иванов Иван", **fields}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_who_keeps_the_directory(client, tokens, access):
    boss, clerk = tokens.bearer("boss"), tokens.bearer("clerk")
    assert (await client.get(f"{API}/people")).status_code == 401
    # the system administrator and administrators of buildings do; others do not
    person = await add(client, tokens.admin())
    await add(client, boss, full_name="Петрова Анна")
    assert (await client.post(f"{API}/people", json={"full_name": "x"}, headers=clerk)).status_code == 403
    assert (await client.get(f"{API}/people", headers=clerk)).status_code == 403
    assert (await client.get(f"{API}/people/{person['id']}", headers=clerk)).status_code == 403
    # name and position by id are open to anyone signed in — nothing more
    brief = await client.post(f"{API}/people/batch-get", json={"ids": [person["id"]]}, headers=clerk)
    assert brief.json()["items"] == [{"id": person["id"], "full_name": "Иванов Иван", "position": ""}]
    # the access service away: the directory is not changed on a guess
    access.up = False
    down = await client.post(f"{API}/people", json={"full_name": "x"}, headers=tokens.bearer("someone-new"))
    assert down.status_code == 503 and down.json()["code"] == "access_unavailable"


async def test_create_find_change_leave(client, app, tokens):
    boss = tokens.bearer("boss")
    p = await add(client, boss, position="врач", department="Эндоскопия", email="Ivanov@Example.test", phone="123")
    assert p["email"] == "ivanov@example.test" and p["linked"] is False and p["status"] == "active"
    await add(client, boss, full_name="Петрова Анна", department="Регистратура")

    found = (await client.get(f"{API}/people", params={"q": "иван"}, headers=boss)).json()["items"]
    assert [x["id"] for x in found] == [p["id"]]
    by_dep = (await client.get(f"{API}/people", params={"department": "Регистратура"}, headers=boss)).json()["items"]
    assert [x["full_name"] for x in by_dep] == ["Петрова Анна"]

    r = await client.patch(f"{API}/people/{p['id']}", json={"position": "заведующий", "version": 1}, headers=boss)
    assert r.json()["position"] == "заведующий" and r.json()["version"] == 2
    stale = await client.patch(f"{API}/people/{p['id']}", json={"position": "x", "version": 1}, headers=boss)
    assert stale.status_code == 409 and stale.json()["current"]["position"] == "заведующий"
    bad = await client.post(f"{API}/people", json={"full_name": "x", "email": "not-an-email"}, headers=boss)
    assert bad.status_code == 422 and bad.json()["errors"][0]["field"] == "email"

    left = await client.post(f"{API}/people/{p['id']}/leave", headers=boss)
    assert left.json()["status"] == "left"
    active = (await client.get(f"{API}/people", headers=boss)).json()["items"]
    assert [x["full_name"] for x in active] == ["Петрова Анна"]
    happened = await events(app)
    assert [e["type"] for e in happened] == ["people.person.created", "people.person.created",
                                             "people.person.changed", "people.person.left"]
    assert happened[2]["data"] == {"person_id": p["id"], "fields": ["position"]}      # which fields, not the values


async def test_first_sign_in_links_the_account_by_email(client, app, tokens):
    boss = tokens.bearer("boss")
    p = await add(client, boss, email="ivanov@example.test")
    me = tokens.bearer("kc-ivanov", email="Ivanov@example.test")

    first = (await client.get(f"{API}/me", headers=me)).json()
    assert first["person"]["id"] == p["id"] and first["reason"] is None
    assert (await client.get(f"{API}/me", headers=me)).json()["person"]["id"] == p["id"]
    linked = [e for e in await events(app) if e["type"] == "people.person.linked"]
    assert [e["data"] for e in linked] == [{"person_id": p["id"], "user_sub": "kc-ivanov"}]      # once

    # nobody with this e-mail; and an account with no e-mail at all
    assert (await client.get(f"{API}/me", headers=tokens.bearer("kc-x", email="x@example.test"))).json() == {
        "person": None, "reason": "unknown"}
    assert (await client.get(f"{API}/me", headers=tokens.bearer("kc-y", email=None))).json()["reason"] == "unknown"

    # the person leaves: the account is nobody again
    await client.post(f"{API}/people/{p['id']}/leave", headers=boss)
    assert (await client.get(f"{API}/me", headers=me)).json() == {"person": None, "reason": "left"}


async def test_shared_email_is_linked_by_hand(client, app, tokens):
    boss = tokens.bearer("boss")
    a = await add(client, boss, full_name="Иванов Иван", email="reception@example.test")
    b = await add(client, boss, full_name="Петрова Анна", email="reception@example.test")
    me = tokens.bearer("kc-anna", email="reception@example.test")
    assert (await client.get(f"{API}/me", headers=me)).json() == {"person": None, "reason": "ambiguous"}

    r = await client.put(f"{API}/people/{b['id']}/link", json={"user_sub": "kc-anna"}, headers=boss)
    assert r.status_code == 200 and r.json()["linked"] is True
    assert (await client.get(f"{API}/me", headers=me)).json()["person"]["id"] == b["id"]
    taken = await client.put(f"{API}/people/{a['id']}/link", json={"user_sub": "kc-anna"}, headers=boss)
    assert taken.status_code == 409 and taken.json()["code"] == "account_taken"

    assert (await client.delete(f"{API}/people/{b['id']}/link", headers=boss)).json()["linked"] is False
    assert [e["type"] for e in await events(app)][-2:] == ["people.person.linked", "people.person.unlinked"]


def workbook(*rows) -> bytes:
    wb = Workbook()
    for row in (("ФИО", "Должность", "Подразделение", "Почта", "Телефон"), *rows):
        wb.active.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


async def test_import_from_excel(client, tokens):
    boss = tokens.bearer("boss")

    async def load(data: bytes):
        return await client.post(f"{API}/people/import", files={"file": ("people.xlsx", data)}, headers=boss)

    rows = [("Иванов Иван", "врач", "Эндоскопия", "ivanov@example.test", "101"),
            ("Петрова Анна", "медсестра", "Эндоскопия", None, None),
            ("Сидоров Пётр", "инженер", "АХО", "не почта", None),
            (None, None, None, None, None),
            ("", "без имени", "", "", "")]
    r = await load(workbook(*rows))
    assert r.status_code == 200
    report = r.json()
    assert (report["created"], report["updated"], report["unchanged"]) == (2, 0, 0)
    assert [e["row"] for e in report["errors"]] == [4, 6] and "email" in report["errors"][0]["message"]

    # the same file again creates nobody
    again = (await load(workbook(*rows))).json()
    assert (again["created"], again["updated"], again["unchanged"]) == (0, 0, 2)
    # a changed row updates the person it is about
    rows[0] = ("Иванов Иван", "заведующий", "Эндоскопия", "ivanov@example.test", "101")
    changed = (await load(workbook(*rows))).json()
    assert (changed["created"], changed["updated"], changed["unchanged"]) == (0, 1, 1)
    people = (await client.get(f"{API}/people", headers=boss)).json()["items"]
    assert [(p["full_name"], p["position"]) for p in people] == [("Иванов Иван", "заведующий"),
                                                                 ("Петрова Анна", "медсестра")]

    assert (await load(b"not a workbook")).status_code == 422
    assert (await client.post(f"{API}/people/import", files={"file": ("p.xlsx", workbook())},
                              headers=tokens.bearer("clerk"))).status_code == 403
