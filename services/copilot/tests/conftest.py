# ruff: noqa: E501
"""The copilot under test: a scratch database, tokens signed here, stand-ins for the other services (a building
with rooms, objects and people, rights by `World.admins`) and a fake OpenAI-compatible model answering from a script."""
from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from twin_chassis.client import ServiceClient
from twin_chassis.testing import Tokens, running, scratch_database, test_settings

from app.main import SERVICE, build

API = "/api/copilot/v1"
BUILDING, FLOOR, ROOM214, ROOM215, OTHER_BUILDING, OTHER_ROOM = (str(uuid4()) for _ in range(6))
MONITOR, PRINTER = str(uuid4()), str(uuid4())
PETROV = str(uuid4())


class World:
    """What the other services answer; records who asked (the `sub` of every token seen)."""

    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.admins: set[str] = set()                 # subs that administer BUILDING
        self.asked: list[tuple[str, str, str]] = []   # (sub, method, path)
        self.rooms = {
            ROOM214: {"id": ROOM214, "building_id": BUILDING, "floor_id": FLOOR, "number": "214", "name": "Кабинет",
                      "type": "office", "area": 18.4, "status": "active"},
            ROOM215: {"id": ROOM215, "building_id": BUILDING, "floor_id": FLOOR, "number": "215", "name": "Серверная",
                      "type": "technical", "area": 12.0, "status": "active"},
        }
        self.assets = {
            MONITOR: {"id": MONITOR, "type_name": "Монитор 24\"", "inventory_no": "00123", "state": "in_use",
                      "building_id": BUILDING, "floor_id": FLOOR, "room_id": ROOM214, "responsible_id": PETROV,
                      "props": {"warranty_until": "2026-10-20", "service_due": "2026-10-25"}, "version": 1},
            PRINTER: {"id": PRINTER, "type_name": "Принтер лазерный", "inventory_no": "00124", "state": "faulty",
                      "building_id": BUILDING, "floor_id": FLOOR, "room_id": ROOM214, "responsible_id": None,
                      "props": {"service_due": "2027-01-10"}, "version": 2},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        me = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        self.asked.append((me.sub, request.method, path))
        if path.endswith("/me/scopes"):
            grants = [{"id": "g1", "person_id": PETROV, "role": "admin", "scope": {"kind": "building", "id": BUILDING},
                       "building_id": BUILDING, "origin": "manual"}] if me.sub in self.admins else []
            return httpx.Response(200, json={"admin": me.is_admin, "service": False, "person_id": None,
                                             "buildings": [BUILDING], "grants": grants})
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/rooms") and request.method == "GET":
            if request.url.params.get("building_id") != BUILDING:
                return httpx.Response(404, json={"code": "not_found", "detail": "Здание не найдено"})
            q = (request.url.params.get("q") or "").lower()
            items = [r for r in self.rooms.values() if q in r["number"].lower() or q in r["name"].lower()]
            return httpx.Response(200, json={"items": items, "next": None})
        if path.endswith("/rooms/batch-get"):
            return httpx.Response(200, json={"items": [self.rooms[i] for i in body["ids"] if i in self.rooms]})
        if "/buildings/v1/rooms/" in path:
            r = self.rooms.get(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json=r) if r else httpx.Response(404, json={"code": "not_found", "detail": "Нет такого помещения"})
        if path.endswith("/assets") and request.method == "GET":
            p = request.url.params
            items = [a for a in self.assets.values()
                     if (not p.get("room_id") or a["room_id"] == p["room_id"])
                     and (not p.get("building_id") or a["building_id"] == p["building_id"])]
            for name, value in p.items():
                if name.startswith("prop."):
                    key, _, op = name[5:].partition(".")
                    items = [a for a in items if (v := a["props"].get(key)) is not None and (
                        v >= value if op == "gte" else v <= value if op == "lte" else v == value)]
            return httpx.Response(200, json={"items": items, "total": len(items), "next": None})
        if "/assets/v1/assets/" in path:
            a = self.assets.get(path.split("/assets/")[-1].split("/")[0])
            if a is None:
                return httpx.Response(404, json={"code": "not_found", "detail": "Объект не найден"})
            if path.endswith("/history"):
                return httpx.Response(200, json={"items": [{"at": "2026-10-01T10:00:00Z", "action": "created"}]})
            return httpx.Response(200, json={**a, "schema": {"properties": [
                {"key": "warranty_until", "title": "Гарантия до", "kind": "date"},
                {"key": "service_due", "title": "Срок ТО", "kind": "date"}]}, "can": {"edit": False}})
        if path.endswith("/people/batch-get"):
            return httpx.Response(200, json={"items": [{"id": PETROV, "full_name": "Петров П. П.", "position": "врач"}]
                                             if PETROV in body["ids"] else []})
        if "/people/v1/rooms/" in path and path.endswith("/people"):
            return httpx.Response(200, json={"items": [{"id": PETROV, "full_name": "Петров П. П.", "position": "врач"}]})
        return httpx.Response(404, json={"code": "not_found", "detail": f"stub: {path}"})


class FakeModel:
    """An OpenAI-compatible /chat/completions: answers from a script, records the requests."""

    def __init__(self):
        self.script: list = []
        self.requests: list[dict] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "fake-model"}, {"id": "other"}]})
        body = json.loads(req.content)
        self.requests.append({"headers": dict(req.headers), "body": body})
        step = self.script.pop(0) if self.script else {"text": "(сценарий закончился)"}
        if isinstance(step, httpx.Response):
            return step
        if not body.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": step.get("text", "")}}],
                                             "usage": {"prompt_tokens": 50, "completion_tokens": 5}})
        chunks = [{"choices": [{"index": 0, "delta": {"reasoning_content": "м" * 150}}]} for _ in range(step.get("reasoning", 0))]
        if step.get("text"):
            for part in (step["text"][:5], step["text"][5:]):
                chunks.append({"choices": [{"index": 0, "delta": {"content": part}}]})
        for i, (name, args) in enumerate(step.get("calls", [])):
            raw = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
            chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": i, "id": f"call_{len(self.requests)}_{i}", "type": "function",
                 "function": {"name": name, "arguments": raw[:7]}}]}}]})
            chunks.append({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": i, "function": {"arguments": raw[7:]}}]}}]})
        chunks.append({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        sse = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def world(tokens) -> World:
    return World(tokens)


@pytest.fixture
def model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens, world, model):
    settings = test_settings(SERVICE, database_url)
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    client = ServiceClient(settings, {s: f"http://{s}.test" for s in
                                      ("access", "buildings", "import", "catalog", "assets", "people", "journal", "planning")}, http)
    model_http = httpx.AsyncClient(transport=httpx.MockTransport(model.handler))
    async with running(build(settings, tokens.verifier(), client, model_http)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def configure(client, tokens, **more) -> dict:
    """The system administrator sets the fake model up and enables the copilot."""
    r = await client.put(f"{API}/settings", headers=tokens.admin(), json={
        "base_url": "http://llm.test/v1", "model": "fake-model", "enabled": True, **more})
    assert r.status_code == 200, r.text
    return r.json()


def events(r: httpx.Response) -> list[dict]:
    """The events of an SSE answer."""
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    out = []
    for frame in r.text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:]))
    return out
