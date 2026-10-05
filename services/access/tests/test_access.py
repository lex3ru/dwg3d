"""Grants, scopes and checks."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from twin_chassis.db import outbox

from .conftest import API

B1, B2, FLOOR, ROOM = (str(uuid4()) for _ in range(4))


def grant(person: str, role: str, kind: str = "building", scope: str = B1, building: str = B1) -> dict:
    return {"person_id": person, "role": role, "scope": {"kind": kind, "id": scope}, "building_id": building}


async def scopes(client, headers) -> dict:
    return (await client.get(f"{API}/me/scopes", headers=headers)).json()


async def test_who_has_what_by_default(client, tokens, people):
    assert (await client.get(f"{API}/me/scopes")).status_code == 401
    nothing = {"admin": False, "service": False, "person_id": None, "grants": [], "buildings": []}
    assert await scopes(client, tokens.admin()) == {**nothing, "admin": True}
    # another service reads everything and changes nothing
    service = tokens.bearer("svc", login="twin-svc-x", service=True)
    assert await scopes(client, service) == {**nothing, "service": True}
    area = [{"kind": "building", "id": B1}]
    r = await client.post(f"{API}/check", json={"checks": [{"action": "view", "chain": area},
                                                           {"action": "manage", "chain": area}]}, headers=service)
    assert [x["allowed"] for x in r.json()["results"]] == [True, False]
    # an account that is no person of the directory has nothing
    assert await scopes(client, tokens.bearer("stranger")) == nothing
    person, headers = await people.person("ivanov")
    assert await scopes(client, headers) == {**nothing, "person_id": person}


async def test_admin_of_a_building_gives_rights_in_it_and_only_in_it(client, app, tokens, people):
    boss, boss_h = await people.person("boss")
    clerk, clerk_h = await people.person("clerk")
    _, stranger_h = await people.person("stranger")

    # the system administrator makes someone the administrator of a building
    r = await client.post(f"{API}/grants", json=grant(boss, "admin"), headers=tokens.admin())
    assert r.status_code == 201 and r.json()["origin"] == "manual"
    assert (await scopes(client, boss_h))["buildings"] == [B1]

    # who gives a floor to a colleague
    r = await client.post(f"{API}/grants", json=grant(clerk, "viewer", "floor", FLOOR), headers=boss_h)
    assert r.status_code == 201
    mine = await scopes(client, clerk_h)
    assert mine["buildings"] == [B1] and [g["scope"] for g in mine["grants"]] == [{"kind": "floor", "id": FLOOR}]
    twice = await client.post(f"{API}/grants", json=grant(clerk, "viewer", "floor", FLOOR), headers=boss_h)
    assert twice.status_code == 409 and twice.json()["code"] == "exists"

    # not in another building, and not as someone who only looks
    other = await client.post(f"{API}/grants", json=grant(clerk, "viewer", scope=B2, building=B2), headers=boss_h)
    assert other.status_code == 404
    assert (await client.post(f"{API}/grants", json=grant(clerk, "admin"), headers=clerk_h)).status_code == 403
    assert (await client.get(f"{API}/grants", params={"building_id": B1}, headers=clerk_h)).status_code == 403
    assert (await client.get(f"{API}/grants", params={"building_id": B1}, headers=stranger_h)).status_code == 404
    assert (await client.post(f"{API}/grants", json=grant(clerk, "owner"), headers=boss_h)).status_code == 422
    mismatch = await client.post(f"{API}/grants", json=grant(clerk, "viewer", "building", B2, B1), headers=boss_h)
    assert mismatch.status_code == 422

    listed = (await client.get(f"{API}/grants", params={"building_id": B1}, headers=boss_h)).json()["items"]
    assert [(g["person_id"], g["role"]) for g in listed] == [(boss, "admin"), (clerk, "viewer")]

    # revoked: gone at once
    floor_grant = next(g for g in listed if g["person_id"] == clerk)
    assert (await client.delete(f"{API}/grants/{floor_grant['id']}", headers=clerk_h)).status_code == 403
    assert (await client.delete(f"{API}/grants/{floor_grant['id']}", headers=boss_h)).status_code == 204
    assert (await client.delete(f"{API}/grants/{floor_grant['id']}", headers=boss_h)).status_code == 404
    assert (await scopes(client, clerk_h))["buildings"] == []
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        events = [(e["type"], e["person_id"], e["building_id"]) for (e,) in rows]
    assert events == [("access.grant.created", boss, B1), ("access.grant.created", clerk, B1),
                      ("access.grant.revoked", clerk, B1)]


async def test_what_a_role_allows(client, tokens, people):
    viewer, viewer_h = await people.person("viewer")
    keeper, keeper_h = await people.person("keeper")
    admin = tokens.admin()
    await client.post(f"{API}/grants", json=grant(viewer, "viewer", "floor", FLOOR), headers=admin)
    await client.post(f"{API}/grants", json=grant(keeper, "responsible", "room", ROOM), headers=admin)
    room = [{"kind": "room", "id": ROOM}, {"kind": "floor", "id": FLOOR}, {"kind": "building", "id": B1}]

    async def can(headers, action, chain) -> bool:
        r = await client.post(f"{API}/check", json={"checks": [{"action": action, "chain": chain}]}, headers=headers)
        return r.json()["results"][0]["allowed"]

    # a floor's viewer sees what is in its rooms, and the plan of the whole building; changes nothing
    assert await can(viewer_h, "view", room) and await can(viewer_h, "plan", room[2:])
    assert not await can(viewer_h, "edit", room) and not await can(viewer_h, "manage", room)
    assert not await can(viewer_h, "view", [{"kind": "floor", "id": B2}, {"kind": "building", "id": B1}])
    assert not await can(viewer_h, "plan", [{"kind": "building", "id": B2}])
    # who answers for a room edits and moves what is portable there, but does not manage
    assert await can(keeper_h, "edit", room) and await can(keeper_h, "move_portable", room)
    assert not await can(keeper_h, "manage", room) and not await can(keeper_h, "edit", room[1:])
    assert await can(admin, "manage", room)
    bad = await client.post(f"{API}/check", json={"checks": [{"action": "destroy", "chain": room}]}, headers=admin)
    assert bad.status_code == 422


async def test_someone_who_left_has_no_rights(client, app, tokens, people):
    person, headers = await people.person("leaver")
    await client.post(f"{API}/grants", json=grant(person, "admin"), headers=tokens.admin())
    await client.post(f"{API}/grants", json=grant(person, "viewer", "floor", FLOOR), headers=tokens.admin())
    assert (await scopes(client, headers))["buildings"] == [B1]

    await people.event("person-left", "people.person.left", {"person_id": person})
    assert (await scopes(client, headers))["person_id"] is None and (await scopes(client, headers))["grants"] == []
    listed = await client.get(f"{API}/grants", params={"building_id": B1}, headers=tokens.admin())
    assert listed.json()["items"] == []
    async with app.state.db.begin() as session:
        rows = await session.execute(select(outbox.c.payload).order_by(outbox.c.created_at, outbox.c.id))
        assert [e["type"] for (e,) in rows][-2:] == ["access.grant.revoked", "access.grant.revoked"]


async def test_unlinked_account_and_scopes_for_services(client, tokens, people):
    person, headers = await people.person("ivanov")
    await client.post(f"{API}/grants", json=grant(person, "viewer"), headers=tokens.admin())
    service = tokens.bearer("svc", login="twin-svc-gateway", service=True)
    by_person = await client.get(f"{API}/scopes", params={"person_id": person}, headers=service)
    assert by_person.json()["buildings"] == [B1]
    assert (await client.get(f"{API}/scopes", params={"person_id": person}, headers=headers)).status_code == 403

    await people.event("person-unlinked", "people.person.unlinked", {"person_id": person, "user_sub": "ivanov"})
    assert (await scopes(client, headers))["grants"] == []          # the grant waits for the person's next account
    relinked = await people.person("ivanov")
    assert relinked[0] != person
