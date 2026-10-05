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
    assert p["status"] == "open" and p["counts"] == {"create": 2, "update": 1, "delete": 0, "layers": 0} and p["agent"] == "Копилот"
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


def test_layer_operations(world, api):  # noqa: F811
    """Layers and variants in proposals: they run first; copies have ids to change at once."""
    pid, layer, editor, owner = world["pid"], world["layer"], world["editor"], world["owner"]
    a = Tools("tok-editor", pid)
    p = a.call("propose_changes", drawing=pid, summary="Вариант с кушеткой у окна и слой камер", ops=[
        {"op": "copy_layer", "layer": layer, "id": "var1abcd", "name": "Мебель — у окна"},
        {"op": "update", "id": "couch1-var1ab", "version": 1, "at": [4, 1]},
        {"op": "create_layer", "kind": "cctv", "id": "cams0001"},
        {"op": "create", "layer": "cams0001", "floor": "c0", "item": "sec.dome", "at": [0.5, 3.5]},
        {"op": "update_layer", "layer": layer, "name": "Мебель — как есть"}])
    assert "error" not in p, p
    assert p["counts"] == {"create": 1, "update": 1, "delete": 0, "layers": 3}
    assert {x["id"] for x in a.call("project_overview")["layers"]} == {layer}          # nothing yet
    pv = editor.get(f"/api/proposals/{p['id']}").json()["preview"]
    assert [(x["op"], x.get("objects")) for x in pv["layers"]] == [("copy_layer", 1), ("create_layer", None), ("update_layer", None)]
    assert pv["updated"][0]["after"]["at"] == [4, 1] and pv["created"][0]["layer"] == "cams0001"
    assert {x["id"] for x in a.call("project_overview")["layers"]} == {layer}          # the preview changed nothing

    done = editor.post(f"/api/proposals/{p['id']}/apply").json()
    assert [x["op"] for x in done["layers"]] == ["copy_layer", "create_layer", "update_layer"]
    ov = {x["id"]: x for x in a.call("project_overview")["layers"]}
    assert ov[layer]["name"] == "Мебель — как есть" and ov["var1abcd"]["variant_group"] == layer
    assert ov["cams0001"]["kind"] == "cctv" and ov["cams0001"]["objects"] == 1
    assert a.call("get_object", id="couch1")["at"] == [2.0, 2.0]                         # the original stays
    cmp = a.call("compare_variants", a=layer, b="var1abcd")
    assert cmp["counts"]["moved"] == 1 and cmp["objects"][0]["change"] == "moved"
    log = owner.get(f"/api/projects/{pid}/audit").json()
    assert "tok-editor · по предложению копилота" in {x["actor"] for x in log if x["entity"] == "layer"}

    # what a person decides: not the lock; a locked layer is not deleted
    assert "человек" in a.call("propose_changes", drawing=pid, summary="x",
                               ops=[{"op": "update_layer", "layer": layer, "locked": False}])["error"]
    assert owner.patch(f"/api/projects/{pid}/layers/{layer}", json={"locked": True}).status_code == 200
    assert "заблокирован" in a.call("propose_changes", drawing=pid, summary="x", ops=[{"op": "delete_layer", "layer": layer}])["error"]
    assert "error" in a.call("propose_changes", drawing=pid, summary="x", ops=[{"op": "copy_layer", "layer": "nope"}])
    assert "error" in a.call("propose_changes", drawing=pid, summary="x", ops=[{"op": "create_layer", "kind": "cctv", "id": "bad id!"}])
    # deleting a variant with its objects
    d = a.call("propose_changes", drawing=pid, summary="Убрать вариант", ops=[{"op": "delete_layer", "layer": "var1abcd"}])
    assert editor.get(f"/api/proposals/{d['id']}").json()["preview"]["layers"] == [
        {"op": "delete_layer", "id": "var1abcd", "name": "Мебель — у окна", "objects": 1}]
    assert editor.post(f"/api/proposals/{d['id']}/apply").status_code == 200
    assert "var1abcd" not in {x["id"] for x in a.call("project_overview")["layers"]}
    assert "error" in a.call("get_object", id="couch1-var1ab")
