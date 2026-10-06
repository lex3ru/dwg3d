"""The planning service under test: a scratch database, tokens signed here, and stand-ins for access (who
administers the building), assets (objects kept in memory, with versions, as the real service checks them)
and catalog (types with prices) behind its HTTP client."""
from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from twin_chassis.client import ServiceClient
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings

from app.main import SERVICE, build

API = "/api/planning/v1"
BUILDING, FLOOR, ROOM = (str(uuid4()) for _ in range(3))
DESK, CHAIR = str(uuid4()), str(uuid4())


class World:
    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.admins = {"boss"}
        self.assets: dict[str, dict] = {}
        self.types = {DESK: {"id": DESK, "name": "Рабочий стол", "category_id": "c", "price": 12000.0, "currency": "RUB"},
                      CHAIR: {"id": CHAIR, "name": "Кресло посетителя", "category_id": "c", "price": 3500.0, "currency": "RUB"}}

    def put(self, type_id: str, number: str, x: float, y: float = 1.0) -> dict:
        a = {"id": str(uuid4()), "type_id": type_id, "type_name": self.types[type_id]["name"], "building_id": BUILDING,
             "floor_id": FLOOR, "room_id": ROOM, "x": x, "y": y, "angle": 0, "inventory_no": number, "note": "",
             "props": {}, "state": "in_use", "container_id": None, "version": 1}
        self.assets[a["id"]] = a
        return a

    def touch(self, asset_id: str, **change) -> None:
        """Someone changes the object in the fact."""
        self.assets[asset_id].update(change)
        self.assets[asset_id]["version"] += 1

    def handle(self, request: httpx.Request) -> httpx.Response:
        url, path = str(request.url), request.url.path
        if url.startswith(ISSUER):
            return httpx.Response(200, json={"access_token": self.tokens.make("svc", service=True, login="svc"), "expires_in": 300})
        me = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        if path.endswith("/me/scopes"):
            grants = [{"role": "admin", "scope": {"kind": "building", "id": BUILDING}, "building_id": BUILDING}]
            return httpx.Response(200, json={"admin": False, "person_id": None, "buildings": [BUILDING],
                                             "grants": grants if me.sub in self.admins else []})
        if "/catalog/" in path:
            return httpx.Response(200, json={"items": list(self.types.values()) if request.url.params.get("active") == "true" else []})
        body = json.loads(request.content) if request.content else {}
        if path.endswith("/assets") and request.method == "GET":
            items = [a for a in self.assets.values() if a["state"] != "retired"]
            return httpx.Response(200, json={"items": items, "total": len(items), "next": None})
        if path.endswith("/assets") and request.method == "POST":
            if any(a["inventory_no"] == body["inventory_no"] for a in self.assets.values()):
                return httpx.Response(409, json={"code": "inventory_no_taken", "detail": "Такой инвентарный номер уже есть"})
            a = self.put(body["type_id"], body["inventory_no"], body["x"], body["y"])
            return httpx.Response(201, json=a)
        asset_id = path.split("/assets/")[-1].split("/")[0]
        a = self.assets.get(asset_id)
        if a is None:
            return httpx.Response(404, json={"code": "not_found"})
        if request.method == "GET":
            return httpx.Response(200, json=a)
        if body.get("version") != a["version"]:
            return httpx.Response(409, json={"code": "version_conflict", "detail": "Объект изменил кто-то другой"})
        if path.endswith("/move"):
            self.touch(asset_id, **{k: body[k] for k in ("floor_id", "x", "y", "angle") if k in body})
        elif path.endswith("/state"):
            self.touch(asset_id, state=body["state"])
        else:
            self.touch(asset_id, note=body.get("note", a["note"]))
        return httpx.Response(200, json=self.assets[asset_id])


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def world(tokens) -> World:
    return World(tokens)


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens, world):
    settings = test_settings(SERVICE, database_url)
    http = httpx.AsyncClient(transport=httpx.MockTransport(world.handle))
    client = ServiceClient(settings, {"access": "http://access.test", "assets": "http://assets.test",
                                      "catalog": "http://catalog.test"}, http)
    async with running(build(settings, tokens.verifier(), client)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
