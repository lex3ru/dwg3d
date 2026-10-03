"""The copilot's tools (agent_tools.py), called as the copilot calls them: as a user, in a project."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from conftest import add_drawing  # noqa: F401
from dwg3d import access, agent_tools, auth, copilot, db
from dwg3d.models import User
from test_auth import _drawing, api, kc, sign_in  # noqa: F401  (fixtures)


def _setup(api, kc):  # noqa: F811
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


class Tools:
    """The tools as the copilot calls them for `login` in project `pid` (copilot.identity + call_tool)."""

    def __init__(self, login: str, pid: str):
        with db.session() as s:
            u = s.scalar(select(User).where(User.login == login))
            me = auth.Me(u.id, u.login, u.name or u.login, u.role, u.email, roles=tuple(u.roles or ()))
            role = access.project_role(s, me, pid)
        self.me = copilot.identity(me, role, pid)

    def call(self, tool: str, **args) -> dict:
        """The tool's JSON answer; an error as {"error": text}."""
        text_, error, data = asyncio.run(copilot.call_tool(self.me, tool, args))
        if error:
            return {"error": text_}
        return data if data is not None else json.loads(text_)


@pytest.fixture
def world(kc, api):  # noqa: F811
    owner, editor, viewer, pid, layer = _setup(api, kc)
    with db.session() as s:     # a room on the floor, an object in it
        fid = s.execute(text("SELECT id FROM floors WHERE drawing_id = :d"), {"d": pid}).scalar()
        rid = s.execute(text("INSERT INTO rooms (drawing_id, floor_id, idx, name, type, area, poly) VALUES "
                             "(:d, :f, 0, 'Кабинет врача', 'office', 20, :p) RETURNING id"),
                        {"d": pid, "f": fid, "p": json.dumps([[[0, 0], [5, 0], [5, 4], [0, 4], [0, 0]]])}).scalar()
    assert editor.post(f"/api/drawings/{pid}/objects", json={"item": "doc.couch", "at": [2, 2], "floor": "c0",
                                                              "layer": layer, "id": "couch1"}).status_code == 201
    with db.session() as s:
        s.execute(text("UPDATE layer_objects SET room_id = :r WHERE id = 'couch1'"), {"r": rid})
    return {"owner": owner, "editor": editor, "viewer": viewer, "pid": pid, "layer": layer, "room": rid}


def test_no_external_agents(world, api):  # noqa: F811
    """No MCP endpoint, no agents' tokens: the tools are the copilot's only."""
    pid, editor = world["pid"], world["editor"]
    with TestClient(api.app) as c:
        c.cookies = editor.cookies
        r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code in (404, 405) and "jsonrpc" not in r.text          # nothing serves it
        assert c.get(f"/api/projects/{pid}/agent-tokens").status_code in (404, 405)
        c.headers["Authorization"] = "Bearer dwg3d_anything"
        c.cookies.clear()
        assert c.get("/api/projects").status_code == 401           # a bearer token is no sign-in
    with pytest.raises(Exception, match="только копилоту"):
        asyncio.run(agent_tools.mcp.call_tool("project_overview", {}))


def test_identity(world):
    pid = world["pid"]
    ed, vw = Tools("tok-editor", pid), Tools("tok-viewer", pid)
    assert ed.me.agent["mode"] == "propose" and vw.me.agent["mode"] == "read"
    assert ed.call("project_overview")["my_role"] == "viewer"          # proposing needs only reading
    assert vw.call("project_overview")["mode"] == "read"
    assert "только на просмотр" in vw.call("propose_changes", drawing=pid, summary="x",
                                           ops=[{"op": "delete", "id": "couch1", "version": 1}])["error"]
    # removed from the project: nothing more
    with db.session() as s:
        s.execute(text("DELETE FROM project_members WHERE project_id = :p AND user_id = "
                       "(SELECT id FROM users WHERE login = 'tok-viewer')"), {"p": pid})
    assert "error" in Tools("tok-viewer", pid).call("project_overview")


def test_read_tools(world):
    pid = world["pid"]
    a = Tools("tok-editor", pid)
    tools = {t.name: t for t in asyncio.run(agent_tools.mcp.list_tools())}
    reading = {"project_overview", "list_rooms", "layer_kinds", "search_catalog", "query_objects",
               "get_object", "report", "recent_changes", "proposal_status", "camera_coverage", "get_ui_context",
               "compare_variants", "list_comments"}
    assert set(tools) == reading | {"propose_changes", "place_in_room", "place_row", "show_in_viewer", "add_comment"}
    assert all(t.annotations.read_only_hint == (n in reading) for n, t in tools.items())
    assert "ctx" not in tools["list_rooms"].input_schema["properties"]

    ov = a.call("project_overview")
    assert ov["mode"] == "propose"
    assert ov["drawings"][0]["floors"] == [{"id": "c0", "name": "1 этаж", "level": None, "elevation": None,
                                            "height": None, "rooms": 1}]
    assert [(x["id"], x["objects"]) for x in ov["layers"]] == [(world["layer"], 1)]

    rooms = a.call("list_rooms", drawing=pid)["rooms"]
    assert rooms == [{"id": world["room"], "floor": "c0", "floor_name": "1 этаж", "name": "Кабинет врача",
                      "type": "office", "area": 20.0, "center": rooms[0]["center"], "bbox": [0.0, 0.0, 5.0, 4.0]}]
    assert a.call("list_rooms", drawing=pid, query="склад")["rooms"] == []
    assert "outline" in a.call("list_rooms", drawing=pid, outline=True)["rooms"][0]
    assert "error" in a.call("list_rooms", drawing="nope")
    assert "error" in a.call("list_rooms", drawing=pid, floor="c9")
    assert "error" in a.call("list_rooms", drawing=pid, floor=7)            # argument validation

    assert "route" in {g for k in a.call("layer_kinds")["kinds"] for g in k["geoms"]}
    cat = a.call("search_catalog")
    assert "items" not in cat and {"security", "fire"} <= {x["id"] for x in cat["categories"]}
    found = a.call("search_catalog", query="doc.couch")["items"]
    assert found[0]["id"] == "doc.couch" and len(found[0]["size"]) == 3

    objs = a.call("query_objects", drawing=pid, floor="c0")
    assert objs["total"] == 1 and not objs["truncated"]
    o = objs["objects"][0]
    assert o["id"] == "couch1" and o["at"] == [2.0, 2.0] and o["room"] == world["room"]
    assert o["room_name"] == "Кабинет врача" and o["item_name"]
    assert a.call("query_objects", room=world["room"])["total"] == 1
    assert a.call("query_objects", item="doc.")["total"] == 1
    assert a.call("query_objects", item="security.")["total"] == 0
    assert a.call("query_objects", bbox=[1.5, 1.5, 2.5, 2.5])["total"] == 1
    assert a.call("query_objects", bbox=[10, 10, 11, 11])["total"] == 0
    assert "error" in a.call("query_objects", floor="c0")
    assert a.call("get_object", id="couch1")["version"] == 1
    assert "error" in a.call("get_object", id="nope")

    assert a.call("report", kind="equipment")["qty"] == 1
    assert a.call("report", kind="checks") == {"fire": []}
    assert "object" in {x["entity"] for x in a.call("recent_changes", limit=5)["changes"]}


def test_comments(world):
    """Comments on the model: read with plan coordinates and rooms; added by the copilot of an editor."""
    pid, room = world["pid"], world["room"]
    ed, vw = Tools("tok-editor", pid), Tools("tok-viewer", pid)
    assert ed.call("list_comments", drawing=pid)["comments"] == []
    c = ed.call("add_comment", drawing=pid, object="couch1", text="Кушетка закрывает розетку?")
    assert c["floor"] == "c0" and c["at"] == [2.0, 2.0] and c["author"] == "Копилот · Имя tok-editor"
    ed.call("add_comment", drawing=pid, room=room, text="Проверить вентиляцию")
    ed.call("add_comment", drawing=pid, floor="c0", at=[4.5, 3.5], text="Здесь дверь?")
    got = vw.call("list_comments", drawing=pid)["comments"]
    assert len(got) == 3 and {x["kind"] for x in got} == {"comment"}
    by_text = {x["text"]: x for x in got}
    assert by_text["Кушетка закрывает розетку?"]["at"] == [2.0, 2.0]                 # back to plan coordinates
    assert by_text["Кушетка закрывает розетку?"]["room_name"] == "Кабинет врача"
    assert [x["text"] for x in vw.call("list_comments", drawing=pid, query="дверь")["comments"]] == ["Здесь дверь?"]
    assert "error" in ed.call("add_comment", drawing=pid, text="без места")
    assert "error" in ed.call("add_comment", drawing=pid, object="nope", text="x")
    assert "только на просмотр" in vw.call("add_comment", drawing=pid, room=room, text="x")["error"]
    # people see them as pins of the drawing
    pins = world["editor"].get(f"/api/drawings/{pid}/pins").json()["comments"]
    assert len(pins) == 3 and pins[0]["pos"][1] == 1.5
