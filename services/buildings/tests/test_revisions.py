"""A build that would retire rooms waits as a draft; the administrator corrects and publishes, or discards.
Rooms merged and split by hand."""
from __future__ import annotations

import copy
from uuid import uuid4

from .conftest import API, DATA, grant
from .test_publish import events, room_ids, tree


def changed_drawing() -> dict:
    """The office of floor 1 split in two; on floor 2 the room without a name gone, the office renamed."""
    data = copy.deepcopy(DATA["split"])
    plan = data["plans"]["c0"]
    plan["rooms"] = [r for r in plan["rooms"] if r["name"]]
    plan["rooms"][0]["name"] = "Ординаторская"
    return data


async def drafts(client, tokens, building) -> list[dict]:
    items = (await client.get(f"{API}/buildings/{building['id']}/revisions", headers=tokens.admin())).json()["items"]
    return [r for r in items if r["status"] == "draft"]


async def test_draft_changes_nothing_until_corrected_and_published(client, app, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")
    before = room_ids(await tree(client, tokens, building))
    plan_before = (await client.get(f"{API}/floors/{(await tree(client, tokens, building))[1]['id']}/plan",
                                    headers=admin)).json()
    model_before = (await client.get(f"{API}/buildings/{building['id']}/model", headers=admin)).json()
    await site.build(changed_drawing())

    # nothing changed: the rooms, the plan, the model; only the draft is there, with its event
    assert room_ids(await tree(client, tokens, building)) == before
    floors = await tree(client, tokens, building)
    assert (await client.get(f"{API}/floors/{floors[1]['id']}/plan", headers=admin)).json() == plan_before
    assert (await client.get(f"{API}/buildings/{building['id']}/model", headers=admin)).json() == model_before
    assert [e["type"] for e in await events(app)][-1] == "buildings.revision.drafted"
    assert len(await events(app, "buildings.revision.published")) == 1
    (draft,) = await drafts(client, tokens, building)
    listed = (await client.get(f"{API}/buildings/{building['id']}/drawings", headers=admin)).json()["items"][0]
    assert listed["revision"]["status"] == "draft" and listed["build_n"] == 1

    # the differences: one room new, the office changed in outline, the other renamed, one room retired
    r = (await client.get(f"{API}/revisions/{draft['id']}", headers=admin)).json()
    d = r["differences"]
    assert d["count"] == {"new": 1, "same": 1, "changed": 2, "retired": 1, "merged": 0, "floors_new": 0,
                          "floors_retired": 0}
    by = {(x["candidate"], x["idx"]): x for x in d["rooms"]}
    assert by[("c1", 1)]["changes"] == ["outline"] and by[("c1", 1)]["room_id"] == before[(1, "Кабинет", 48.69)]
    assert by[("c1", 2)]["changes"] == ["new"]
    assert by[("c0", 0)]["changes"] == ["name"] and by[("c0", 0)]["old_name"] == "Кабинет"
    assert [x["id"] for x in d["retired"]] == [before[(2, "", 34.78)]]
    assert {c["id"] for c in d["choices"][floors[0]["id"]]} == {before[(1, "Кабинет", 48.69)], before[(1, "", 34.78)]}

    # the administrator says: the office continues in the smaller part (where its door is)
    office = before[(1, "Кабинет", 48.69)]
    fixed = await client.patch(f"{API}/revisions/{draft['id']}/matches", headers=admin,
                               json={"matches": [{"candidate": "c1", "idx": 2, "room_id": office}]})
    assert fixed.status_code == 200
    by = {(x["candidate"], x["idx"]): x for x in fixed.json()["differences"]["rooms"]}
    assert by[("c1", 2)]["room_id"] == office and by[("c1", 2)]["auto"] is False and by[("c1", 1)]["room_id"] is None
    elsewhere = {"candidate": "c1", "idx": 2, "room_id": before[(2, "Кабинет", 48.69)]}
    wrong = await client.patch(f"{API}/revisions/{draft['id']}/matches", headers=admin, json={"matches": [elsewhere]})
    assert wrong.status_code == 422                                        # a room of another floor
    assert (await client.post(f"{API}/revisions/{draft['id']}/publish",
                              headers=grant(site.importer, "viewer", "viewer", "building", building["id"],
                                            building["id"]))).status_code == 403

    published = await client.post(f"{API}/revisions/{draft['id']}/publish", headers=admin)
    assert published.status_code == 200 and published.json()["status"] == "published"
    after = room_ids(await tree(client, tokens, building))
    assert after[(1, "", 17.44)] == office                 # its name is what the drawing says of that part: none
    assert after[(1, "", 34.78)] == before[(1, "", 34.78)]
    assert after[(2, "Ординаторская", 48.69)] == before[(2, "Кабинет", 48.69)]
    retired = await events(app, "buildings.room.retired")
    assert [e["data"]["room_id"] for e in retired] == [before[(2, "", 34.78)]]
    assert (await client.post(f"{API}/revisions/{draft['id']}/publish", headers=admin)).status_code == 409


async def test_discarded_draft_leaves_no_trace(client, app, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")
    before = room_ids(await tree(client, tokens, building))
    await site.build(changed_drawing())
    (draft,) = await drafts(client, tokens, building)
    gone = await client.post(f"{API}/revisions/{draft['id']}/discard", headers=admin)
    assert gone.status_code == 200 and gone.json()["status"] == "discarded"
    assert room_ids(await tree(client, tokens, building)) == before
    assert await drafts(client, tokens, building) == []
    assert [e["type"] for e in await events(app)][-1] == "buildings.revision.discarded"
    assert await events(app, "buildings.room.retired") == []
    # the next build is looked at afresh
    await site.build(changed_drawing())
    assert len(await drafts(client, tokens, building)) == 1


async def test_a_newer_draft_replaces_an_older_one(client, tokens, building, site):
    await site.build("base")
    await site.build(changed_drawing())
    await site.build(changed_drawing())
    url = f"{API}/buildings/{building['id']}/revisions"
    revisions = (await client.get(url, headers=tokens.admin())).json()["items"]
    assert [r["status"] for r in revisions] == ["draft", "discarded", "published"]
    assert revisions[1]["decided_by"] == "superseded"


async def test_rooms_merged_and_split_by_hand(client, app, tokens, building, site):
    admin = tokens.admin()
    await site.build("base")
    floors = await tree(client, tokens, building)
    first, second = floors[0], floors[1]
    office = next(r for r in second["rooms"] if r["name"] == "Кабинет")
    other = next(r for r in second["rooms"] if r["name"] == "")
    merged = await client.post(f"{API}/rooms/{office['id']}/merge", json={"with": [other["id"]]}, headers=admin)
    assert merged.status_code == 200 and merged.json()["area"] == round(48.69 + 34.78, 2)
    assert (await client.get(f"{API}/rooms/{other['id']}", headers=admin)).json()["status"] == "retired"
    # a point of the room that was merged is in the heir now; the plan shows one outline
    located = await client.post(f"{API}/floors/{second['id']}/locate", json={"points": [[2.0, 4.0]]}, headers=admin)
    assert located.json()["rooms"] == [office["id"]]
    plan = (await client.get(f"{API}/floors/{second['id']}/plan", headers=admin)).json()["plan"]
    assert [r["id"] for r in plan["rooms"] if r["poly"]] == [office["id"]]
    event = (await events(app, "buildings.room.merged"))[0]
    assert event["data"] == {"from": [other["id"]], "into": office["id"], "floor_id": second["id"]}
    far = next(r for r in first["rooms"] if r["name"] == "Кабинет")
    assert (await client.post(f"{API}/rooms/{office['id']}/merge", json={"with": [far["id"]]},
                              headers=admin)).status_code == 422            # another floor

    # the office of floor 1 split by a line from wall to wall: the larger part keeps the room
    split = await client.post(f"{API}/rooms/{far['id']}/split", json={"line": [[8.5, -1], [8.5, 10]]}, headers=admin)
    assert split.status_code == 200
    parts = {r["id"]: r for r in split.json()["rooms"]}
    assert split.json()["heir"] == far["id"] and len(parts) == 2
    new = next(i for i in parts if i != far["id"])
    points = {"points": [[6.0, 4.0], [10.0, 4.0]]}
    located = await client.post(f"{API}/floors/{first['id']}/locate", json=points, headers=admin)
    assert located.json()["rooms"] == [far["id"], new]
    plan = (await client.get(f"{API}/floors/{first['id']}/plan", headers=admin)).json()["plan"]
    assert {r["id"] for r in plan["rooms"]} >= {far["id"], new}
    event = (await events(app, "buildings.room.split"))[0]
    assert event["data"] == {"from": far["id"], "into": [new], "heir": far["id"], "floor_id": first["id"]}
    assert (await client.post(f"{API}/rooms/{new}/split", json={"line": [[50, 50], [60, 60]]},
                              headers=admin)).status_code == 422
    stranger = grant(site.importer, "viewer", "viewer", "building", building["id"], building["id"])
    assert (await client.post(f"{API}/rooms/{new}/split", json={"line": [[9, -1], [9, 10]]},
                              headers=stranger)).status_code == 403
    assert (await client.post(f"{API}/rooms/{uuid4()}/merge", json={"with": [new]}, headers=admin)).status_code == 404
