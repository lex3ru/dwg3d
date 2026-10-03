"""What the user's windows show, for their agents; view commands to those windows only."""
import json
import threading

import httpx
from fastapi.testclient import TestClient

from dwg3d import auth, events
from test_agent_mcp import Agent, world  # noqa: F401  (fixture)
from test_auth import api, kc  # noqa: F401  (fixtures)
from test_events import live  # noqa: F401  (fixture)

CLIENT = "tab-0123456789"


def test_ui_context(world, api):  # noqa: F811
    pid, editor, owner = world["pid"], world["editor"], world["owner"]
    url = f"/api/projects/{pid}/ui-context"
    with TestClient(api.app) as c:
        a = Agent(c, world["write"])                   # the editor's agent
        assert a.call("get_ui_context")["windows"] == []
        assert editor.post(url, json={"client": "x"}).status_code == 400
        assert editor.post(url, json={"client": CLIENT, "drawing": pid, "floor": "c0", "view": "2d",
                                      "selected": ["couch1", 7], "room": world["room"], "tool": "furniture"}).status_code == 204
        owner.post(url, json={"client": "owner-tab-123456", "drawing": pid, "floor": "c0", "view": "3d"})
        ws = a.call("get_ui_context")["windows"]
        assert len(ws) == 1                            # the owner's window is not the editor's
        w = ws[0]
        assert w["drawing"]["id"] == pid and w["floor"] == {"id": "c0", "name": "1 этаж"} and w["view"] == "2d"
        assert w["room"]["name"] == "Кабинет врача" and w["tool"] == "furniture"
        assert [x["id"] for x in w["selected"]] == ["couch1"] and w["selected"][0]["name"]
        # agents read it, they do not write it
        agent_http = TestClient(api.app)
        agent_http.headers["Authorization"] = f"Bearer {world['write']}"
        assert agent_http.post(url, json={"client": CLIENT, "drawing": pid}).status_code == 403
        # the window closes
        assert editor.post(url, json={"client": CLIENT, "closed": True}).status_code == 204
        assert a.call("get_ui_context")["windows"] == []

        # commands: checked, told when nobody looks
        r = a.call("show_in_viewer", objects=["couch1"], label="Кушетка")
        assert r["sent"]["highlight"] == ["couch1"] and r["sent"]["floor"] == "c0" and r["windows"] == 0 and r["note"]
        assert a.call("show_in_viewer", room=world["room"])["sent"]["room"] == world["room"]
        assert "error" in a.call("show_in_viewer")
        assert "error" in a.call("show_in_viewer", objects=["nope"])
        assert "error" in a.call("show_in_viewer", floor="c0")          # no drawing open, none given
        editor.post(url, json={"client": CLIENT, "drawing": pid, "floor": "c0"})
        r = a.call("show_in_viewer", floor="c0", view="3d")              # the open drawing by default
        assert r["sent"] == {"drawing": pid, "floor": "c0", "view": "3d"} and r["windows"] == 1


def test_commands_reach_only_the_users_windows(world, api, live, monkeypatch):  # noqa: F811
    pid, editor, owner = world["pid"], world["editor"], world["owner"]
    monkeypatch.setattr(events, "HEARTBEAT", 0.5)
    got: dict[str, list] = {"editor": [], "owner": []}

    def watch(who, client):
        with httpx.Client(base_url=live, timeout=10) as h, \
                h.stream("GET", f"/api/projects/{pid}/events", cookies={auth.COOKIE: client.cookies.get(auth.COOKIE)}) as r:
            for line in r.iter_lines():
                if line.startswith("data:") and '"view"' in line:
                    got[who].append(json.loads(line[5:]))
                    return

    ts = [threading.Thread(target=watch, args=(w, c), daemon=True) for w, c in (("editor", editor), ("owner", owner))]
    for t in ts:
        t.start()
    assert events.ready.wait(10)
    threading.Event().wait(1.0)                         # both streams subscribed
    with TestClient(api.app) as c:
        Agent(c, world["write"]).call("show_in_viewer", objects=["couch1"], label="Вот она")
    ts[0].join(10)
    ts[1].join(2)                                       # the owner gets nothing: still waiting
    assert len(got["editor"]) == 1 and got["owner"] == []
    ev = got["editor"][0]
    assert ev["entity"] == "view" and ev["agent"] == "Claude-w"
    assert ev["command"]["highlight"] == ["couch1"] and ev["command"]["label"] == "Вот она"
