"""Events are kept once and shown to those who see their area."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select

from app.handlers import row_of
from app.models import events

from .conftest import A1, API, P1, P2, R1, R2, B, F, happened


async def test_feed_by_area_and_by_right(client, app, tokens, access):
    seen = await happened(app, "assets.asset.changed", ("asset", A1), {"asset_id": A1, "changes": {}},
                          actor={"kind": "user", "id": "u-1", "person_id": P1},
                          building_id=B, floor_id=F, room_id=R1, asset_id=A1)
    await happened(app, "buildings.room.changed", ("room", R2), {"room_id": R2, "fields": ["name"]},
                   building_id=B, floor_id=F, room_id=R2)
    await happened(app, "buildings.building.changed", ("building", B), {"name": "x"}, building_id=B)
    await happened(app, "people.person.linked", ("person", P2), {"person_id": P2, "user_sub": "u-2"}, person_id=P2)
    # the same event again: kept once
    assert await app.state.bus.handle("journal", seen) is False
    async with app.state.db.begin() as session:
        assert len((await session.execute(select(events.c.id))).scalars().all()) == 4

    admin = tokens.admin()
    whole = (await client.get(f"{API}/events", headers=admin)).json()["items"]
    assert [e["type"] for e in whole] == ["people.person.linked", "buildings.building.changed",
                                         "buildings.room.changed", "assets.asset.changed"]
    assert whole[3]["actor"] == {"kind": "user", "id": "u-1", "person_id": P1} and whole[3]["asset_id"] == A1
    assert (await client.get(f"{API}/events/{seen['id']}", headers=admin)).json()["type"] == "assets.asset.changed"

    # whoever sees room 1 sees what happened in it — and nothing of room 2 or of the building as a whole
    viewer = access.person("viewer", P1, ("viewer", "room", R1))
    mine = (await client.get(f"{API}/events", params={"building_id": B}, headers=viewer)).json()["items"]
    assert [e["type"] for e in mine] == ["assets.asset.changed"]
    assert (await client.get(f"{API}/events/{whole[1]['id']}", headers=viewer)).status_code == 404
    by_room = (await client.get(f"{API}/events", params={"room_id": R2}, headers=viewer)).json()["items"]
    assert by_room == []
    # the building's administrator sees all of it
    boss = access.person("boss", P2, ("admin", "building", B))
    theirs = (await client.get(f"{API}/events", params={"building_id": B}, headers=boss)).json()["items"]
    assert len(theirs) == 3
    # a person's own events are theirs even without a building; someone else's are not
    own = (await client.get(f"{API}/events", params={"person_id": P2}, headers=boss)).json()["items"]
    assert [e["type"] for e in own] == ["people.person.linked"]
    assert (await client.get(f"{API}/events", params={"person_id": P2}, headers=viewer)).status_code == 403
    assert (await client.get(f"{API}/events", headers=viewer)).status_code == 403
    assert (await client.get(f"{API}/events")).status_code == 401


async def test_filters_and_pages(client, app, tokens):
    for n in range(7):
        await happened(app, "assets.asset.state_changed" if n % 2 else "assets.asset.changed", ("asset", A1),
                       {"asset_id": A1, "n": n}, building_id=B, floor_id=F, room_id=R1, asset_id=A1)
    admin = tokens.admin()
    by_type = (await client.get(f"{API}/events", params={"building_id": B, "type": "assets.asset.changed"},
                                headers=admin)).json()["items"]
    assert [e["data"]["n"] for e in by_type] == [6, 4, 2, 0]
    by_prefix = (await client.get(f"{API}/events", params={"asset_id": A1, "type": "assets."}, headers=admin)).json()
    assert len(by_prefix["items"]) == 7
    first = (await client.get(f"{API}/events", params={"asset_id": A1, "limit": 3}, headers=admin)).json()
    assert [e["data"]["n"] for e in first["items"]] == [6, 5, 4] and first["next"]
    second = (await client.get(f"{API}/events", params={"asset_id": A1, "limit": 3, "cursor": first["next"]},
                               headers=admin)).json()
    assert [e["data"]["n"] for e in second["items"]] == [3, 2, 1]
    since = (await client.get(f"{API}/events", params={"asset_id": A1, "from": first["items"][1]["time"]},
                              headers=admin)).json()["items"]
    assert [e["data"]["n"] for e in since] == [6, 5]


async def test_old_events_are_forgotten(app):
    fresh = await happened(app, "assets.asset.changed", ("asset", A1), {"asset_id": A1}, building_id=B, asset_id=A1)
    old = dict(fresh, id="0192f000-0000-7000-8000-0000000000ff",
               time=(datetime.now(UTC) - timedelta(days=40)).isoformat().replace("+00:00", "Z"))
    async with app.state.db.begin() as session:
        await session.execute(insert(events).values(**row_of(old)))
    assert await app.state.forget_old() == 1
    async with app.state.db.begin() as session:
        kept = (await session.execute(select(events.c.id))).scalars().all()
    assert [str(k) for k in kept] == [fresh["id"]]


async def test_a_guest_by_a_link_sees_no_feed(client, app, tokens):
    seen = await happened(app, "assets.asset.changed", ("asset", A1), {"asset_id": A1, "changes": {}},
                          actor={"kind": "user", "id": "u-1", "person_id": P1},
                          building_id=B, floor_id=F, room_id=R1, asset_id=A1)
    # the feed tells who did what: not even of the guest's own floor, nor one event by its id
    guest = tokens.guest("floor", F, B, F)
    asks = [("GET", f"{API}/events", {"building_id": B}), ("GET", f"{API}/events", {"floor_id": F}),
            ("GET", f"{API}/events", {"asset_id": A1}), ("GET", f"{API}/events/{seen['id']}", {})]
    assert {path.replace(seen["id"], "{event_id}") for _, path, _ in asks} == set(app.openapi()["paths"])
    for method, path, params in asks:
        r = await client.request(method, path, params=params, headers=guest)
        assert (r.status_code, r.json()["code"]) == (403, "guest"), (path, params, r.text)
    whole = tokens.guest("building", B, B)
    assert (await client.get(f"{API}/events", params={"building_id": B}, headers=whole)).status_code == 403
