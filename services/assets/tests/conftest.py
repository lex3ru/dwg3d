"""The assets service under test: a scratch database, a bucket of its own, tokens signed here, and
stand-ins for the three services it asks — access (who may what), buildings (the room of a point),
catalog (the schema of a type) — behind its HTTP client. No real neighbour is needed."""
from __future__ import annotations

import os
import secrets
from uuid import uuid4

os.environ["TWIN_S3_BUCKET"] = f"test-assets-{secrets.token_hex(4)}"
os.environ.setdefault("TWIN_S3_ENDPOINT", os.environ.get("TWIN_TEST_S3_ENDPOINT", "http://127.0.0.1:9002"))

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from twin_chassis.client import ServiceClient  # noqa: E402
from twin_chassis.testing import ISSUER, Tokens, running, scratch_database, test_settings  # noqa: E402

from app import storage  # noqa: E402
from app.main import SERVICE, build  # noqa: E402

API = "/api/assets/v1"
BUILDING, FLOOR, ROOM_A, ROOM_B = (str(uuid4()) for _ in range(4))
CATEGORY = str(uuid4())


def prop(key, title, kind="text", by="admin", required=False, **kw) -> dict:
    return {"key": key, "title": title, "kind": kind, "unit": None, "options": None, "required": required,
            "stored": "asset", "editable_by": by, "set": None, "set_id": None, **kw}


def kind(name: str, *props, portable=False, container=False) -> dict:
    return {"id": str(uuid4()), "name": name, "category_id": CATEGORY, "container": container, "portable": portable,
            "active": True, "schema_version": 1, "schema": [
                *props, {**prop("maker", "Производитель"), "stored": "type", "editable_by": "system"}]}


class World:
    """What the service sees through its HTTP client."""

    def __init__(self, tokens: Tokens):
        self.tokens = tokens
        self.grants: dict[str, list[dict]] = {}          # account -> grants
        self.persons: dict[str, str] = {}                # account -> person id
        self.up = {"access": True, "buildings": True, "catalog": True}
        self.forget = lambda: None                      # drops what the service remembers of anyone's scopes
        self.scope = prop("service_next", "Дата следующего ТО", "date", by="responsible")
        self.types = {
            "scope": kind("Гастроскоп", self.scope, prop("made", "Год выпуска", "number"),
                          prop("owner", "Владелец", required=True), portable=True),
            "couch": kind("Кушетка", prop("wear", "Износ", "choice", by="responsible",
                                          options=[{"value": "good", "title": "хороший"}, {"value": "worn", "title": "изношен"}])),
            "rack": kind("Стойка", container=True),
        }

    def person(self, sub: str, *grants: tuple[str, str, str]) -> dict[str, str]:
        """An account with a person behind it and grants (role, scope kind, scope id) in BUILDING; its headers."""
        self.persons[sub] = self.persons.get(sub) or str(uuid4())
        self.grants[sub] = [{"role": r, "scope": {"kind": k, "id": i}, "building_id": BUILDING} for r, k, i in grants]
        self.forget()                                   # as if the 20 s of remembering had passed
        return self.tokens.bearer(sub)

    def handle(self, request: httpx.Request) -> httpx.Response:
        url, path = str(request.url), request.url.path
        if url.startswith(ISSUER):
            token = self.tokens.make("svc-assets", login="twin-svc-assets", service=True)
            return httpx.Response(200, json={"access_token": token, "expires_in": 300})
        service = path.split("/")[2]
        if not self.up[service]:
            raise httpx.ConnectError(f"{service} is down")
        if service == "access":
            me = self.tokens.verifier().identity(request.headers["authorization"].removeprefix("Bearer "))
            grants = self.grants.get(me.sub, [])
            return httpx.Response(200, json={"admin": False, "service": False, "person_id": self.persons.get(me.sub),
                                             "grants": grants, "buildings": [BUILDING] if grants else []})
        if service == "buildings":                       # two rooms side by side: x in [0, 5) and [5, 10)
            import json
            if not path.endswith(f"/floors/{FLOOR}/locate"):
                return httpx.Response(404, json={"code": "not_found"})
            rooms = [ROOM_A if 0 <= x < 5 else ROOM_B if 5 <= x < 10 else None
                     for x, _ in json.loads(request.content)["points"]]
            return httpx.Response(200, json={"building_id": BUILDING, "rooms": rooms})
        found = next((t for t in self.types.values() if path.endswith(f"/types/{t['id']}")), None)
        return httpx.Response(200, json=found) if found else httpx.Response(404, json={"code": "not_found"})


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
def world(tokens) -> World:
    return World(tokens)


@pytest.fixture
def database_url():
    with scratch_database() as url:
        yield url


@pytest_asyncio.fixture
async def app(database_url, tokens, world):
    settings = test_settings(SERVICE, database_url)
    services = {name: f"http://{name}.test" for name in ("access", "buildings", "catalog")}
    client = ServiceClient(settings, services, httpx.AsyncClient(transport=httpx.MockTransport(world.handle)))
    async with running(build(settings, tokens.verifier(), client)) as app:
        world.forget = app.state.rights.forget
        yield app


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
def boss(world) -> dict[str, str]:
    """The administrator of the building."""
    return world.person("boss", ("admin", "building", BUILDING))


async def put(client, headers, world, type_: str, number: str, x: float = 2.0, **kw) -> dict:
    """Place an object of a test type at (x, 2) of the floor."""
    body = {"type_id": world.types[type_]["id"], "floor_id": FLOOR, "x": x, "y": 2.0, "inventory_no": number, **kw}
    if type_ == "scope":
        body.setdefault("props", {"owner": "Эндоскопия"})
    r = await client.post(f"{API}/assets", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
