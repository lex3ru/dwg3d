"""The built-in copilot against a fake OpenAI-compatible endpoint: settings, the tool loop,
proposals, the chat kept, limits, who may use it."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from dwg3d import copilot
from test_agent_tools import world  # noqa: F401  (fixture)
from test_auth import api, kc, sign_in  # noqa: F401  (fixtures)


class FakeModel:
    """An OpenAI-compatible /chat/completions: answers from a script, records the requests."""

    def __init__(self, script):
        self.script, self.requests = list(script), []

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fake-model"}]})
        body = json.loads(req.content)
        self.requests.append({"headers": dict(req.headers), "body": body})
        step = self.script.pop(0)
        if isinstance(step, httpx.Response):
            return step
        if not body.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": step.get("text", "")}}]})
        chunks = [{"choices": [{"index": 0, "delta": {"reasoning": "м" * 150}}]} for _ in range(step.get("reasoning", 0))]
        if step.get("text"):
            for part in (step["text"][:5], step["text"][5:]):
                chunks.append({"choices": [{"index": 0, "delta": {"content": part}}]})
        for i, (name, args) in enumerate(step.get("calls", [])):
            raw = json.dumps(args, ensure_ascii=False)
            chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": i, "id": f"call_{len(self.requests)}_{i}", "type": "function", "function": {"name": name, "arguments": raw[:7]}}]}}]})
            chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": i, "function": {"arguments": raw[7:]}}]}}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        sse = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})


@pytest.fixture
def model(monkeypatch):
    holder = {}

    def use(script):
        holder["fake"] = FakeModel(script)
        return holder["fake"]
    monkeypatch.setattr(copilot, "_client", lambda timeout=300: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: holder["fake"].handler(req))))
    return use


def _events(r) -> list[dict]:
    assert r.status_code == 200, r.text
    return [json.loads(x) for x in r.text.splitlines() if x.strip()]


def _admin(api, kc):  # noqa: F811
    return sign_in(api, kc, "cop-admin", roles=["dwg3d.admin"])


def test_settings(world, api, kc, model):  # noqa: F811
    admin, editor = _admin(api, kc), world["editor"]
    assert editor.get("/api/copilot/settings").status_code == 403
    assert editor.put("/api/copilot/settings", json={"enabled": True}).status_code == 403
    assert admin.put("/api/copilot/settings", json={"enabled": True}).status_code == 400       # no endpoint yet
    assert admin.put("/api/copilot/settings", json={"base_url": "ftp://x"}).status_code == 400
    r = admin.put("/api/copilot/settings", json={"base_url": "http://llm.test/v1/chat/completions", "api_key": "sk-secret-12345678",
                                                 "model": "fake-model", "enabled": True, "daily_limit": 50})
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["base_url"] == "http://llm.test/v1" and cfg["api_key_set"] and cfg["api_key_hint"] == "…5678"
    assert "sk-secret" not in json.dumps(cfg) and "api_key" not in cfg
    # the key stays when not given
    assert admin.put("/api/copilot/settings", json={"daily_limit": 40}).json()["api_key_set"]
    fake = model([{"text": "Готов"}])
    chk = admin.post("/api/copilot/settings/check").json()
    assert chk["ok"] and chk["models"] == ["fake-model"] and chk["answer"] == "Готов" and chk["prompt_tokens"] > 1000
    assert fake.requests[0]["headers"]["authorization"] == "Bearer sk-secret-12345678"
    model([httpx.Response(401, json={"error": "bad key"})])
    bad = admin.post("/api/copilot/settings/check").json()
    assert not bad["ok"] and "401" in bad["error"]
    st = editor.get("/api/copilot/status").json()
    assert st["enabled"] and st["model"] == "fake-model" and st["daily_limit"] == 40


def test_copilot_turn(world, api, kc, model):  # noqa: F811
    pid, room, editor, owner = world["pid"], world["room"], world["editor"], world["owner"]
    _admin(api, kc).put("/api/copilot/settings", json={"base_url": "http://llm.test/v1", "model": "fake-model",
                                                       "enabled": True, "daily_limit": 100})
    fake = model([
        {"text": "Смотрю проект", "calls": [("project_overview", {})]},
        {"calls": [("place_in_room", {"drawing": pid, "room": room, "item": "doc.couch", "then": "propose",
                                      "summary": "Кушетку к стене"}),
                   ("apply_changes", {"drawing": pid, "ops": []})]},
        {"text": "Предложил кушетку у стены — посмотрите предложение справа.", "reasoning": 3},
    ])
    ui = {"client": "tab-abcdefgh", "drawing": pid, "floor": "c0", "view": "2d", "room": room, "selected": ["couch1"]}
    with TestClient(api.app) as c:
        c.cookies = editor.cookies
        ev = _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "Поставь сюда кушетку", "ui": ui}))
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "chat" and kinds[-1] == "done" and "error" not in kinds
    assert [e["name"] for e in ev if e["type"] == "tool"] == ["project_overview", "place_in_room", "apply_changes"]
    assert next(e for e in ev if e["type"] == "tool" and e["name"] == "apply_changes")["error"]      # no such tool
    prop = next(e for e in ev if e["type"] == "proposal")["proposal"]
    assert prop["status"] == "open" and prop["agent"] == "Копилот"
    assert "".join(e["text"] for e in ev if e["type"] == "text").startswith("Смотрю проект")
    assert [e["chars"] for e in ev if e["type"] == "thinking"] == [300]          # reasoning: told, not kept

    # what the model was given: the system prompt, the user's window, tools without direct writing
    first = fake.requests[0]["body"]
    assert first["model"] == "fake-model" and first["stream"] is True and first["messages"][0]["role"] == "system"
    user = first["messages"][1]["content"]
    assert "Сейчас у пользователя открыто" in user and "Кабинет врача" in user and "couch1" in user and user.endswith("Поставь сюда кушетку")
    names = {t["function"]["name"] for t in first["tools"]}
    assert {"place_in_room", "propose_changes", "show_in_viewer"} <= names and "apply_changes" not in names
    # the tool results went back with their call ids, in order
    third = fake.requests[2]["body"]["messages"]
    assert [m["role"] for m in third[1:]] == ["user", "assistant", "tool", "assistant", "tool", "tool"]
    assert all(not k.startswith("_") for m in third for k in m)

    # the proposal is the copilot's, in the user's name; nothing applied
    pr = editor.get(f"/api/projects/{pid}/proposals?status=open").json()
    assert [x["agent"] for x in pr] == ["Копилот"] and pr[0]["user"]["login"] == "tok-editor"
    log = owner.get(f"/api/projects/{pid}/audit").json()
    assert any(x["entity"] == "proposal" and x["actor"] == "tok-editor · Копилот" for x in log)

    # the chat is kept, for its owner only
    cid = ev[0]["id"]
    chats = editor.get(f"/api/projects/{pid}/copilot/chats").json()
    assert [x["id"] for x in chats] == [cid] and chats[0]["title"] == "Поставь сюда кушетку"
    items = editor.get(f"/api/projects/{pid}/copilot/chats/{cid}").json()["items"]
    assert items[0] == {"type": "user", "text": "Поставь сюда кушетку"}
    assert any(i["type"] == "proposal" for i in items) and items[-1]["type"] == "assistant"
    assert owner.get(f"/api/projects/{pid}/copilot/chats/{cid}").status_code == 404
    # usage: three requests to the model
    assert editor.get("/api/copilot/status").json()["used_today"] == 3

    # the conversation goes on in the same chat (history sent back)
    fake = model([{"text": "Да, одна кушетка."}])
    with TestClient(api.app) as c:
        c.cookies = editor.cookies
        _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "Одна?", "chat": cid}))
    assert len(fake.requests[0]["body"]["messages"]) == 1 + 8
    assert editor.delete(f"/api/projects/{pid}/copilot/chats/{cid}").status_code == 204


def test_copilot_limits_and_rights(world, api, kc, model):  # noqa: F811
    pid = world["pid"]
    admin = _admin(api, kc)
    admin.put("/api/copilot/settings", json={"enabled": False})
    with TestClient(api.app) as c:
        c.cookies = world["editor"].cookies
        assert "не настроен" in _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "?"}))[-1]["message"]
    admin.put("/api/copilot/settings", json={"base_url": "http://llm.test/v1", "model": "fake-model", "enabled": True, "daily_limit": 1})

    # a viewer: answers only, no proposing tool offered
    viewer = sign_in(api, kc, "tok-viewer")
    fake = model([{"text": "Здесь две комнаты."}])
    with TestClient(api.app) as c:
        c.cookies = viewer.cookies
        ev = _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "Что тут?"}))
    assert ev[-1]["type"] == "done"
    body = fake.requests[0]["body"]
    assert not {"propose_changes", "place_in_room", "place_row"} & {t["function"]["name"] for t in body["tools"]}
    assert "только на просмотр" in body["messages"][0]["content"]
    # the daily limit
    with TestClient(api.app) as c:
        c.cookies = viewer.cookies
        assert "лимит" in _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "Ещё?"}))[-1]["message"]
    admin.put("/api/copilot/settings", json={"daily_limit": 0})          # 0: no limit

    # the endpoint fails: told, nothing kept
    model([httpx.Response(500, text="overloaded")])
    with TestClient(api.app) as c:
        c.cookies = viewer.cookies
        ev = _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "Ещё?"}))
    assert ev[-1]["type"] == "error" and "500" in ev[-1]["message"]
    # a server that ignores streaming (plain JSON) is read whole
    model([httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Без потока"}}],
                                      "usage": {"prompt_tokens": 5, "completion_tokens": 2}})])
    with TestClient(api.app) as c:
        c.cookies = viewer.cookies
        ev = _events(c.post(f"/api/projects/{pid}/copilot", json={"message": "Ещё?"}))
    assert [e for e in ev if e["type"] == "text"] == [{"type": "text", "text": "Без потока"}] and ev[-1]["type"] == "done"

    # not for guests of links or strangers
    sh = world["owner"].post(f"/api/projects/{pid}/shares", json={}).json()
    guest = TestClient(api.app)
    guest.post(f"/api/share/{sh['token']}")
    assert guest.post(f"/api/projects/{pid}/copilot", json={"message": "?"}).status_code == 403
    assert guest.get(f"/api/projects/{pid}/copilot/chats").status_code == 403
    stranger = sign_in(api, kc, "cop-stranger")
    assert stranger.post(f"/api/projects/{pid}/copilot", json={"message": "?"}).status_code == 404
