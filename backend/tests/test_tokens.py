"""Tokens of AI agents: one project, the user's role capped by the token's mode."""
from fastapi.testclient import TestClient
from sqlalchemy import text

from dwg3d import db, tokens
from test_auth import _drawing, api, kc, sign_in  # noqa: F401  (fixtures)


def _agent(api, token):
    c = TestClient(api.app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _setup(api, kc):
    """An owner, an editor and a viewer of a project with a drawing (one floor) and a layer."""
    owner = sign_in(api, kc, "tok-owner")
    editor = sign_in(api, kc, "tok-editor")
    viewer = sign_in(api, kc, "tok-viewer")
    did = _drawing()
    with db.session() as s:
        uid = {r.login: r.id for r in s.execute(text("SELECT id, login FROM users WHERE login LIKE 'tok-%'"))}
        for login, role in (("tok-owner", "owner"), ("tok-editor", "editor"), ("tok-viewer", "viewer")):
            s.execute(text("INSERT INTO project_members (project_id, user_id, role) VALUES (:p, :u, :r)"),
                      {"p": did, "u": uid[login], "r": role})
    layer = owner.post(f"/api/projects/{did}/layers", json={"kind": "furniture"}).json()["id"]
    return owner, editor, viewer, did, layer


def test_agent_tokens(kc, api):
    owner, editor, viewer, pid, layer = _setup(api, kc)
    other = owner.post("/api/projects", json={"name": "Другой"}).json()["id"]
    url = f"/api/projects/{pid}/agent-tokens"

    # who may make what
    assert viewer.post(url, json={"mode": "write"}).status_code == 403
    assert viewer.post(url, json={"mode": "boss"}).status_code == 400
    assert editor.post(url, json={"mode": "write", "days": 0}).status_code == 400
    assert editor.post(url, json={"mode": "write", "days": 1000}).status_code == 400
    ro = viewer.post(url, json={"name": "Claude (чтение)", "mode": "read"}).json()
    rw = editor.post(url, json={"name": "Claude", "mode": "write", "days": 30}).json()
    assert ro["token"].startswith(tokens.PREFIX) and rw["mode"] == "write" and rw["active"]
    # listing: without the token; the own ones, an owner all
    assert "token" not in editor.get(url).json()[0]
    assert [x["id"] for x in editor.get(url).json()] == [rw["id"]]
    assert {x["id"] for x in owner.get(url).json()} == {ro["id"], rw["id"]}

    a, r = _agent(api, rw["token"]), _agent(api, ro["token"])
    me = a.get("/api/auth/me").json()
    assert me["login"] == "tok-editor" and me["agent"]["project_id"] == pid and me["agent"]["mode"] == "write"
    # one project only
    assert [p["id"] for p in a.get("/api/projects").json()] == [pid]
    assert a.get(f"/api/projects/{pid}").json()["my_role"] == "editor"
    assert a.get(f"/api/projects/{other}").status_code == 404
    assert _agent(api, "dwg3d_wrong").get("/api/projects").status_code == 401
    assert _agent(api, "dwg3d_wrong").get("/api/auth/me").status_code == 401

    # a write token: objects and layers, like an editor
    floor = a.get(f"/api/drawings/{pid}").json()["result"]["floors"][0]["id"]
    obj = {"item": "doc.couch", "at": [2, 2], "floor": floor, "layer": layer, "id": "agent1"}
    assert a.post(f"/api/drawings/{pid}/objects", json=obj).status_code == 201
    v = a.get(f"/api/drawings/{pid}/objects").json()["items"][0]["version"]
    assert a.patch(f"/api/drawings/{pid}/objects/agent1", json={**obj, "at": [3, 3], "version": v}).status_code == 200
    new = a.post(f"/api/projects/{pid}/layers", json={"kind": "cctv"})
    assert new.status_code == 201
    assert a.patch(f"/api/projects/{pid}/layers/{new.json()['id']}", json={"name": "Камеры"}).status_code == 200
    # ...but nothing a person should decide
    assert a.patch(f"/api/projects/{pid}/layers/{layer}", json={"locked": True}).status_code == 403
    assert a.delete(f"/api/projects/{pid}/layers/{layer}").status_code == 403
    assert a.delete(f"/api/projects/{pid}").status_code == 403
    assert a.patch(f"/api/projects/{pid}", json={"name": "x"}).status_code == 403
    assert a.post(f"/api/drawings/{pid}/rebuild", json={}).status_code == 403
    assert a.post(url, json={"mode": "write"}).status_code == 403
    for path in (url, f"/api/projects/{pid}/members", f"/api/projects/{pid}/shares", "/api/users"):
        assert a.get(path).status_code == 403, path
    assert a.patch("/api/catalog/items/doc.couch", json={"price": 1}).status_code == 403

    # a read token: reading only, even of an editor's token mode
    assert r.get(f"/api/drawings/{pid}/objects").status_code == 200
    assert r.get(f"/api/projects/{pid}").json()["my_role"] == "viewer"
    assert r.post(f"/api/drawings/{pid}/objects", json={**obj, "id": "agent2"}).status_code == 403
    assert r.get(f"/api/projects/{pid}/audit").status_code == 200

    # the audit log names the agent
    log = owner.get(f"/api/projects/{pid}/audit").json()
    assert "tok-editor · агент «Claude»" in {x["actor"] for x in log if x["entity"] == "object"}

    # revoking: the author or an owner, not someone else
    assert viewer.delete(f"{url}/{rw['id']}").status_code == 404
    assert owner.delete(f"{url}/{rw['id']}").json()["revoked"] is True
    assert a.get("/api/projects").status_code == 401
    # the user leaves the project: the token opens nothing
    with db.session() as s:
        s.execute(text("DELETE FROM project_members WHERE project_id = :p AND user_id = "
                       "(SELECT id FROM users WHERE login = 'tok-viewer')"), {"p": pid})
    assert r.get(f"/api/projects/{pid}").status_code == 404
    # expired
    t = editor.post(url, json={"mode": "read"}).json()
    with db.session() as s:
        s.execute(text("UPDATE agent_tokens SET expires_at = now() - interval '1 minute' WHERE id = :i"), {"i": t["id"]})
    assert _agent(api, t["token"]).get("/api/projects").status_code == 401


def test_guests_have_no_tokens(kc, api):
    owner, _, _, pid, _ = _setup(api, kc)
    sh = owner.post(f"/api/projects/{pid}/shares", json={}).json()
    guest = TestClient(api.app)
    guest.post(f"/api/share/{sh['token']}")
    assert guest.get(f"/api/projects/{pid}/agent-tokens").status_code == 403
    assert guest.post(f"/api/projects/{pid}/agent-tokens", json={}).status_code == 403


def test_agent_may():
    may = tokens.agent_may
    assert may("GET", "/api/drawings/d/objects", "read")
    assert not may("POST", "/api/drawings/d/objects", "read")
    assert not may("POST", "/api/drawings/d/objects", "propose")
    assert may("POST", "/api/drawings/d/objects:batch", "write")
    assert may("DELETE", "/api/drawings/d/pins/p1", "write")
    assert not may("DELETE", "/api/drawings/d", "write")
    assert not may("POST", "/api/drawings/d/revision", "write")
    assert not may("POST", "/api/projects/p/layers/l/copy", "write")
    assert not may("GET", "/api/projects/p/agent-tokens/x", "write")
