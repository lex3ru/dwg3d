"""The buildings service under test: a scratch database, tokens signed here,
and a stand-in for the import service behind the HTTP client (it serves
results of builds recorded from the real pipeline, tests/data). No other
service is needed."""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
from pathlib import Path
from uuid import uuid4

os.environ["TWIN_S3_BUCKET"] = f"test-buildings-{secrets.token_hex(4)}"
os.environ.setdefault("TWIN_S3_ENDPOINT", os.environ.get("TWIN_TEST_S3_ENDPOINT", "http://127.0.0.1:9002"))

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from twin_chassis.client import ServiceClient  # noqa: E402
from twin_chassis.events import envelope  # noqa: E402
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings  # noqa: E402

from app import storage  # noqa: E402
from app.main import SERVICE, build  # noqa: E402

API = "/api/buildings/v1"
DATA = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (Path(__file__).parent / "data").glob("*.json")}
IMPORT = "http://import.test"


class Import:
    """The import service as buildings sees it."""

    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.builds: dict[str, dict] = {}          # build id -> {n, building_id, result, plans}
        self.up = True
        self.calls: list[str] = []

    def add(self, building_id: str, n: int, fixture: str) -> str:
        build_id = str(uuid4())
        self.builds[build_id] = {"n": n, "building_id": building_id, **copy.deepcopy(DATA[fixture])}
        return build_id

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(ISSUER):                 # the service asks Keycloak for its own token
            token = self.tokens.make("svc-buildings", login="twin-svc-buildings", service=True)
            return httpx.Response(200, json={"access_token": token, "expires_in": 300})
        assert url.startswith(IMPORT), url
        if not self.up:
            raise httpx.ConnectError("import is down")
        caller = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
        assert caller.kind == "service"
        self.calls.append(request.url.path)
        m = re.fullmatch(r"/api/import/v1/builds/([0-9a-f-]+)/(result|files/plans/floor_(\w+)\.json)",
                         request.url.path)
        b = self.builds.get(m.group(1)) if m else None
        if b is None:
            return httpx.Response(404, json={"code": "not_found"})
        if m.group(2) == "result":
            return httpx.Response(200, json={"build": {"id": m.group(1), "n": b["n"]}, "building_id": b["building_id"],
                                             "result": b["result"]})
        return httpx.Response(200, json=b["plans"][m.group(3)])


@pytest.fixture(scope="session", autouse=True)
def _cleanup():
    yield
    bucket = storage.bucket()
    try:
        bucket.delete_prefix("")
        bucket._s3.delete_bucket(Bucket=bucket.name)
    except Exception:
        pass


@pytest.fixture(scope="session")
def tokens() -> Tokens:
    return Tokens()


@pytest.fixture
def importer(tokens) -> Import:
    return Import(tokens)


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens, importer):
    settings = test_settings(SERVICE, database_url)
    http = httpx.AsyncClient(transport=httpx.MockTransport(importer.handle))
    client = ServiceClient(settings, {"import": IMPORT}, http)
    async with running(build(settings, tokens.verifier(), client)) as app:
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def building(client, tokens) -> dict:
    r = await client.post(f"{API}/buildings", json={"name": "Корпус А", "address": "ул. Тестовая, 1"},
                          headers=tokens.admin())
    assert r.status_code == 201, r.text
    return r.json()


class Site:
    """Plays the import service's events into the service under test, as the bus would."""

    def __init__(self, app, importer: Import, building_id: str):
        self.app, self.importer, self.building_id = app, importer, building_id
        self.drawing_id = str(uuid4())
        self.n = 0

    def event(self, type_: str, data: dict) -> dict:
        return envelope(type_, ("drawing", self.drawing_id), data, actor={"kind": "service", "id": "import"},
                        building_id=self.building_id)

    async def upload(self, name: str = "Корпус А.dxf") -> None:
        await self.app.state.bus.handle("drawing-uploaded", self.event(
            "import.drawing.uploaded", {"drawing_id": self.drawing_id, "name": name, "filename": name, "file_n": 1}))

    def finished(self, fixture: str, n: int | None = None) -> dict:
        self.n = n if n is not None else self.n + 1
        build_id = self.importer.add(self.building_id, self.n, fixture)
        return self.event("import.build.finished", {
            "build_id": build_id, "drawing_id": self.drawing_id, "n": self.n, "floors": 2, "rooms": 4,
            "warnings": 0, "quality": "ok"})

    async def build(self, fixture: str = "base", n: int | None = None) -> dict:
        event = self.finished(fixture, n)
        assert await self.app.state.bus.handle("build-finished", event) is True
        return event

    async def delete(self) -> None:
        await self.app.state.bus.handle("drawing-deleted", self.event(
            "import.drawing.deleted", {"drawing_id": self.drawing_id}))


@pytest_asyncio.fixture
async def site(app, importer, building) -> Site:
    s = Site(app, importer, building["id"])
    await s.upload()
    return s
