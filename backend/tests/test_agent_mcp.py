"""MCP for AI agents (/api/mcp): read-only tools as the token's user, in its project."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from dwg3d import db
from test_auth import api, kc, sign_in  # noqa: F401  (fixtures)
from test_tokens import _setup

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


class Agent:
    """JSON-RPC to /api/mcp with a token."""

    def __init__(self, c: TestClient, token: str | None):
        self.c, self.h, self.n = c, {**H, **({"Authorization": f"Bearer {token}"} if token else {})}, 0

    def rpc(self, method: str, params: dict | None = None):
        self.n += 1
        return self.c.post("/api/mcp", headers=self.h,
                           json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})

    def call(self, tool: str, **args) -> dict:
        """The tool's JSON answer; ToolError text as {"error": ...}."""
        r = self.rpc("tools/call", {"name": tool, "arguments": args})
        assert r.status_code == 200, r.text
        res = r.json()["result"]
        body = res["content"][0]["text"] if res.get("content") else ""
        if res.get("isError"):
            return {"error": body}
        return res.get("structuredContent") or json.loads(body)


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
    tok = editor.post(f"/api/projects/{pid}/agent-tokens", json={"name": "Claude", "mode": "read"}).json()["token"]
    return {"owner": owner, "editor": editor, "pid": pid, "layer": layer, "room": rid, "token": tok}


def test_mcp_needs_a_token(world, api):  # noqa: F811
    with TestClient(api.app) as c:
        assert Agent(c, None).rpc("tools/list").status_code == 401
        assert Agent(c, "dwg3d_wrong").rpc("tools/list").status_code == 401
        # a browser session is not an agent
        r = world["editor"].post("/api/mcp", headers=H, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 401


def test_mcp_read_tools(world, api):  # noqa: F811
    pid = world["pid"]
    with TestClient(api.app) as c:
        a = Agent(c, world["token"])
        tools = {t["name"]: t for t in a.rpc("tools/list").json()["result"]["tools"]}
        assert set(tools) == {"project_overview", "list_rooms", "layer_kinds", "search_catalog", "query_objects",
                              "get_object", "report", "recent_changes"}
        assert all(t["annotations"]["readOnlyHint"] for t in tools.values())
        assert "ctx" not in tools["list_rooms"]["inputSchema"]["properties"]

        ov = a.call("project_overview")
        assert ov["my_role"] == "viewer" and ov["token_mode"] == "read"
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
        log = a.call("recent_changes", limit=5)["changes"]
        assert {"object", "agent_token"} <= {x["entity"] for x in log}


def test_mcp_follows_the_token(world, api):  # noqa: F811
    """Revoked or its user out of the project: the tools stop answering."""
    pid = world["pid"]
    with TestClient(api.app) as c:
        a = Agent(c, world["token"])
        assert a.call("project_overview")["project"]["id"] == pid
        with db.session() as s:
            s.execute(text("DELETE FROM project_members WHERE project_id = :p AND user_id = "
                           "(SELECT id FROM users WHERE login = 'tok-editor')"), {"p": pid})
        assert "error" in a.call("project_overview")
        tid = world["owner"].get(f"/api/projects/{pid}/agent-tokens").json()[0]["id"]
        world["owner"].delete(f"/api/projects/{pid}/agent-tokens/{tid}")
        assert a.rpc("tools/list").status_code == 401
