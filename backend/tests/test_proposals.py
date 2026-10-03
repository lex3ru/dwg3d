"""Proposals: made by the copilot, seen, applied or rejected by a person."""
from fastapi.testclient import TestClient

from test_agent_tools import Tools, world  # noqa: F401  (fixture)
from test_auth import api, kc  # noqa: F401  (fixtures)


def test_proposals(world, api):  # noqa: F811
    pid, layer, editor, owner = world["pid"], world["layer"], world["editor"], world["owner"]
    couch = {"op": "create", "layer": layer, "floor": "c0", "item": "doc.couch", "at": [1, 1]}
    a = Tools("tok-editor", pid)
    assert "error" in a.call("propose_changes", drawing=pid, summary="плохо", ops=[{**couch, "item": "no.such"}])
    assert "error" in a.call("propose_changes", drawing=pid, summary="  ", ops=[couch])

    p = a.call("propose_changes", drawing=pid, summary="Две кушетки, первую сдвинуть к окну",
               ops=[couch, {**couch, "at": [3, 1]}, {"op": "update", "id": "couch1", "version": 1, "at": [4, 3]}])
    assert p["status"] == "open" and p["counts"] == {"create": 2, "update": 1, "delete": 0} and p["agent"] == "Копилот"
    # nothing changed yet
    assert a.call("query_objects", drawing=pid)["total"] == 1
    assert a.call("proposal_status", id=p["id"])["status"] == "open"
    assert [x["id"] for x in a.call("proposal_status")["proposals"]] == [p["id"]]
    assert Tools("tok-viewer", pid).call("proposal_status")["proposals"] == []        # the editor's, not the viewer's

    # a person sees it and what it would do
    listed = editor.get(f"/api/projects/{pid}/proposals?status=open").json()
    assert [x["id"] for x in listed] == [p["id"]] and listed[0]["drawing"] and listed[0]["user"]["login"] == "tok-editor"
    full = editor.get(f"/api/proposals/{p['id']}").json()
    pv = full["preview"]
    assert len(pv["created"]) == 2 and pv["deleted"] == []
    assert pv["updated"][0]["before"]["at"] == [2, 2] and pv["updated"][0]["after"]["at"] == [4, 3]
    assert a.call("query_objects", drawing=pid)["total"] == 1          # the preview changed nothing

    # who may decide: editors, not viewers
    assert world["viewer"].post(f"/api/proposals/{p['id']}/apply").status_code == 403
    done = editor.post(f"/api/proposals/{p['id']}/apply")
    assert done.status_code == 200, done.text
    assert done.json()["proposal"]["status"] == "applied" and len(done.json()["items"]) == 3
    assert a.call("query_objects", drawing=pid)["total"] == 3
    st = a.call("proposal_status", id=p["id"])
    assert st["status"] == "applied" and st["decided_by"]["login"] == "tok-editor"
    assert editor.post(f"/api/proposals/{p['id']}/apply").status_code == 400          # once
    log = owner.get(f"/api/projects/{pid}/audit").json()
    assert "tok-editor · по предложению копилота" in {x["actor"] for x in log if x["entity"] == "object"}
    assert {"create", "apply"} <= {x["action"] for x in log if x["entity"] == "proposal"}

    # stale: the rows changed since
    v = a.call("get_object", id="couch1")["version"]
    p2 = a.call("propose_changes", drawing=pid, summary="Убрать кушетку", ops=[{"op": "delete", "id": "couch1", "version": v}])
    assert editor.patch(f"/api/drawings/{pid}/objects/couch1", json={"at": [1, 3], "version": v}).status_code == 200
    st = editor.get(f"/api/proposals/{p2['id']}").json()
    assert st["status"] == "stale" and st["reason"]
    assert editor.post(f"/api/proposals/{p2['id']}/apply").status_code == 400
    assert a.call("proposal_status", id=p2["id"])["status"] == "stale"

    # stale found only at applying: 409, nothing applied
    p3 = a.call("propose_changes", drawing=pid, summary="Ещё одна", ops=[{**couch, "id": "late1"}])
    assert editor.post(f"/api/drawings/{pid}/objects", json={**couch, "id": "late1"}).status_code == 201
    late = editor.post(f"/api/proposals/{p3['id']}/apply")
    assert late.status_code == 409 and late.json()["proposal"]["status"] == "stale"

    # rejected, with the reason for the copilot
    p4 = a.call("propose_changes", drawing=pid, summary="Кушетку в проход", ops=[{**couch, "at": [4.5, 2]}])
    rj = editor.post(f"/api/proposals/{p4['id']}/reject", json={"reason": "Перекрывает проход"})
    assert rj.json()["status"] == "rejected"
    st = a.call("proposal_status", id=p4["id"])
    assert st["status"] == "rejected" and st["reason"] == "Перекрывает проход"
    assert editor.post(f"/api/proposals/{p4['id']}/reject").status_code == 400
    assert a.call("query_objects", drawing=pid)["total"] == 4             # 3 applied + late1


def test_guests_see_no_proposals(world, api):  # noqa: F811
    pid, owner = world["pid"], world["owner"]
    sh = owner.post(f"/api/projects/{pid}/shares", json={}).json()
    guest = TestClient(api.app)
    guest.post(f"/api/share/{sh['token']}")
    assert guest.get(f"/api/projects/{pid}/proposals").status_code == 403
    assert guest.get("/api/proposals/whatever").status_code == 403
