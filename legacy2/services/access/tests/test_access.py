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


async def test_who_answers_for_an_object_may_edit_it(client, app, tokens, people):
    from twin_chassis.events import envelope
    old, old_h = await people.person("old-keeper")
    new, new_h = await people.person("new-keeper")
    asset = str(uuid4())
    chain = [{"kind": "asset", "id": asset}, {"kind": "room", "id": ROOM}, {"kind": "building", "id": B1}]

    async def named(who_from, who_to) -> None:
        data = {"asset_id": asset, "from": who_from, "to": who_to}
        event = envelope("assets.asset.responsible_changed", ("asset", asset), data,
                         actor={"kind": "user", "id": "boss"}, building_id=B1, asset_id=asset)
        assert await app.state.bus.handle("responsible-changed", event) is True

    async def can(headers, action) -> bool:
        r = await client.post(f"{API}/check", json={"checks": [{"action": action, "chain": chain}]}, headers=headers)
        return r.json()["results"][0]["allowed"]

    await named(None, old)
    assert await can(old_h, "edit") and await can(old_h, "plan") and not await can(old_h, "manage")
    assert (await scopes(client, old_h))["grants"][0]["origin"] == "responsible"
    # a right on the same object given by hand is another grant
    await client.post(f"{API}/grants", json=grant(old, "viewer", "asset", asset), headers=tokens.admin())

    await named(old, new)                                   # someone else answers now
    assert await can(new_h, "edit") and not await can(old_h, "edit")
    assert await can(old_h, "view")                         # what was given by hand stays
    await named(new, None)                                  # nobody answers
    assert not await can(new_h, "view")


async def test_assignment_to_a_room_gives_sight_of_it(client, app, tokens, people):
    from twin_chassis.events import envelope
    person, me = await people.person("worker")
    chain = [{"kind": "room", "id": ROOM}, {"kind": "floor", "id": FLOOR}, {"kind": "building", "id": B1}]

    async def can(action) -> bool:
        r = await client.post(f"{API}/check", json={"checks": [{"action": action, "chain": chain}]}, headers=me)
        return r.json()["results"][0]["allowed"]

    async def room_event(type_: str, handler: str) -> None:
        data = {"person_id": person, "building_id": B1, "floor_id": FLOOR, "room_id": ROOM}
        event = envelope(type_, ("person", person), data, actor={"kind": "user", "id": "boss"},
                         building_id=B1, room_id=ROOM, person_id=person)
        assert await app.state.bus.handle(handler, event) is True

    assert not await can("view")
    await room_event("people.person.assigned", "person-assigned")
    assert await can("view") and await can("plan") and not await can("edit")
    assert [g["origin"] for g in (await scopes(client, me))["grants"]] == ["assignment"]
    # given by hand too: the assignment going does not take that away
    await client.post(f"{API}/grants", json=grant(person, "viewer", "room", ROOM), headers=tokens.admin())
    await room_event("people.person.unassigned", "person-unassigned")
    assert await can("view") and [g["origin"] for g in (await scopes(client, me))["grants"]] == ["manual"]
    # the room is no more: every grant on it goes
    gone = envelope("buildings.room.retired", ("room", ROOM), {"room_id": ROOM, "floor_id": FLOOR},
                    actor={"kind": "service", "id": "buildings"}, building_id=B1, room_id=ROOM)
    assert await app.state.bus.handle("room-retired", gone) is True
    assert not await can("view")


async def test_reconciliation_restores_and_removes_automatic_grants(client, app, tokens, people, sources):
    from sqlalchemy import delete

    from app.models import grants as table
    person, me = await people.person("worker")
    other, _ = await people.person("other")
    asset = str(uuid4())
    sources.assignments = [{"person_id": person, "room_id": ROOM, "building_id": B1, "floor_id": FLOOR}]
    sources.responsibles = [{"asset_id": asset, "person_id": person, "building_id": B1}]
    # a stale automatic grant nobody is the source of any more, and a manual one that is nobody's business
    await client.post(f"{API}/grants", json=grant(other, "viewer", "room", ROOM), headers=tokens.admin())
    async with app.state.db.begin() as session:
        from sqlalchemy import insert
        from twin_chassis import uuid7
        await session.execute(insert(table).values(id=uuid7(), person_id=other, role="viewer", scope_kind="room",
                                                   scope_id=ROOM, building_id=B1, origin="assignment"))
    first = await client.post(f"{API}/reconcile", headers=tokens.admin())
    assert first.status_code == 200 and first.json() == {"added": 2, "removed": 1}
    mine = (await scopes(client, me))["grants"]
    assert sorted((g["role"], g["origin"]) for g in mine) == [("responsible", "responsible"), ("viewer", "assignment")]
    assert (await client.post(f"{API}/reconcile", headers=tokens.admin())).json() == {"added": 0, "removed": 0}
    # someone deletes the automatic grant by hand: the next reconciliation brings it back
    async with app.state.db.begin() as session:
        await session.execute(delete(table).where(table.c.person_id == person, table.c.origin == "assignment"))
    assert (await client.post(f"{API}/reconcile", headers=tokens.admin())).json() == {"added": 1, "removed": 0}
    assert (await client.post(f"{API}/reconcile", headers=me)).status_code == 403
    sources.up = False
    assert (await client.post(f"{API}/reconcile", headers=tokens.admin())).status_code == 503


async def test_rights_on_merged_rooms_go_to_the_heir(client, app, tokens, people):
    from twin_chassis.events import envelope
    person, me = await people.person("worker")
    other_room = str(uuid4())
    admin = tokens.admin()
    await client.post(f"{API}/grants", json=grant(person, "viewer", "room", other_room), headers=admin)
    await client.post(f"{API}/grants", json=grant(person, "responsible", "room", other_room), headers=admin)
    await client.post(f"{API}/grants", json=grant(person, "viewer", "room", ROOM), headers=admin)
    merged = envelope("buildings.room.merged", ("room", ROOM), {"from": [other_room], "into": ROOM, "floor_id": FLOOR},
                      actor={"kind": "user", "id": "boss"}, building_id=B1, room_id=ROOM)
    assert await app.state.bus.handle("room-merged", merged) is True
    mine = sorted((g["role"], g["scope"]["id"]) for g in (await scopes(client, me))["grants"])
    assert mine == [("responsible", ROOM), ("viewer", ROOM)]



async def test_a_link_for_guests(client, app, tokens, people):
    from datetime import UTC, datetime, timedelta

    import jwt as pyjwt
    from twin_chassis.db import outbox

    admin = tokens.admin()
    boss, boss_h = await people.person("boss")
    await client.post(f"{API}/grants", json=grant(boss, "admin"), headers=admin)
    later = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    body = {"building_id": B1, "scope": {"kind": "floor", "id": FLOOR}, "expires_at": later, "note": "подрядчик"}
    made = await client.post(f"{API}/shares", json=body, headers=boss_h)
    assert made.status_code == 201
    share = made.json()
    assert share["url"].endswith(f"/s/{share['token']}") and share["state"] == "active" and share["floor_id"] == FLOOR
    # the token is shown once: the list does not have it
    listed = (await client.get(f"{API}/shares", params={"building_id": B1}, headers=boss_h)).json()["items"]
    assert [x["id"] for x in listed] == [share["id"]] and "token" not in listed[0]
    clerk, clerk_h = await people.person("clerk")
    await client.post(f"{API}/grants", json=grant(clerk, "viewer"), headers=admin)
    assert (await client.post(f"{API}/shares", json=body, headers=clerk_h)).status_code == 403
    assert (await client.post(f"{API}/shares", json={**body, "expires_at": "2020-01-01T00:00:00Z"},
                              headers=boss_h)).status_code == 422
    room = {**body, "scope": {"kind": "room", "id": ROOM}}
    assert (await client.post(f"{API}/shares", json=room, headers=boss_h)).status_code == 422      # its floor is needed

    # opened without an account: a guest token for the floor, checked by the published key
    opened = await client.post(f"{API}/shares/open", json={"token": share["token"], "address": "10.0.0.7"})
    assert opened.status_code == 200
    token = opened.json()["token"]
    keys = (await client.get(f"{API}/.well-known/jwks.json")).json()["keys"]
    public = pyjwt.algorithms.RSAAlgorithm.from_jwk(keys[0])
    claims = pyjwt.decode(token, public, algorithms=["RS256"], issuer="twin-access-guest")
    assert claims["area"] == {"kind": "floor", "id": FLOOR} and claims["floor_id"] == FLOOR
    guest = {"Authorization": f"Bearer {token}"}
    mine = await scopes(client, guest)
    assert mine["guest"] == {"kind": "floor", "id": FLOOR, "building_id": B1, "floor_id": FLOOR}
    chain = lambda *area: [{"kind": k, "id": i} for k, i in area]                                   # noqa: E731
    checks = {"checks": [{"action": "view", "chain": chain(("room", ROOM), ("floor", FLOOR), ("building", B1))},
                         {"action": "plan", "chain": chain(("floor", FLOOR), ("building", B1))},
                         {"action": "plan", "chain": chain(("floor", str(uuid4())), ("building", B1))},
                         {"action": "plan", "chain": chain(("building", B1))},
                         {"action": "edit", "chain": chain(("room", ROOM), ("floor", FLOOR), ("building", B1))},
                         {"action": "plan", "chain": chain(("building", B2))}]}
    results = (await client.post(f"{API}/check", json=checks, headers=guest)).json()["results"]
    assert [r["allowed"] for r in results] == [True, True, False, True, False, False]
    assert (await client.get(f"{API}/grants", params={"building_id": B1}, headers=guest)).status_code == 403
    # opening is counted and is an event with the address; renewing is neither
    assert (await client.post(f"{API}/shares/open", json={"token": share["token"], "renew": True})).status_code == 200
    listed = (await client.get(f"{API}/shares", params={"building_id": B1}, headers=boss_h)).json()["items"]
    assert listed[0]["opened"] == 1 and listed[0]["last_opened_at"]
    async with app.state.db.begin() as session:
        opened_events = [e for (e,) in await session.execute(select(outbox.c.payload))
                         if e["type"] == "access.share.opened"]
    assert len(opened_events) == 1 and opened_events[0]["data"]["address"] == "10.0.0.7"
    assert opened_events[0]["building_id"] == B1

    # revoked: opens nothing, nor renews; an unknown token is the same 404
    assert (await client.delete(f"{API}/shares/{share['id']}", headers=boss_h)).status_code == 204
    assert (await client.post(f"{API}/shares/open", json={"token": share["token"]})).status_code == 404
    assert (await client.post(f"{API}/shares/open", json={"token": share["token"], "renew": True})).status_code == 404
    assert (await client.post(f"{API}/shares/open", json={"token": "x" * 32})).status_code == 404
    listed = (await client.get(f"{API}/shares", params={"building_id": B1}, headers=boss_h)).json()["items"]
    assert listed[0]["state"] == "revoked"
    # expired
    soon = await client.post(f"{API}/shares", headers=boss_h,
                             json={**body, "expires_at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat()})
    import asyncio
    await asyncio.sleep(2.5)
    assert (await client.post(f"{API}/shares/open", json={"token": soon.json()["token"]})).status_code == 404
